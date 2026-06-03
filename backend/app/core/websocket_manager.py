"""WebSocket 连接管理 — 本地广播 + Redis pub/sub 跨实例扇出。

架构
----
- ConnectionManager 按 conversation_id 管理 WebSocket 连接池。
- 单实例：publish() → broadcast() 直接写入所有本地连接。
- 多实例（Phase 18）：publish() 同时发布到 Redis 频道，各实例的 Redis 订阅者
  收到消息后调用 broadcast() 写入本地连接，实现跨进程消息同步。

Redis 订阅
----------
每个 API worker 启动一个后台 asyncio Task 订阅 Redis 模式频道
`fastagent:ws:{conversation_id}`，收到消息后反序列化 JSON 并广播到
该会话的所有本地 WebSocket 连接。

设计要点
--------
- Redis 不可用时自动降级：publish() 仅做本地广播（单实例模式下功能不受影响）。
- 连接断开时自动退订 Redis 频道，避免频道泄漏。
- 使用 aioredis 异步客户端，不阻塞 asyncio 事件循环。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """按 conversation_id 管理 WebSocket 连接。

    publish() 同时写入本地连接和 Redis pub/sub，确保多 worker 场景下
    所有实例的 WebSocket 都能收到消息。
    """

    def __init__(self) -> None:
        # conversation_id → set[WebSocket]
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        # employee_id → 活跃连接数（用于判断在线状态）
        self._employee_connections: dict[int, int] = defaultdict(int)
        # Redis 客户端（延迟初始化，首次 publish 时连接）
        self._redis = None
        self._redis_subscriber: asyncio.Task | None = None
        # 已订阅的 conversation_id 集合（用于退订）
        self._subscribed: set[int] = set()

    async def _get_redis(self):
        """延迟初始化 Redis 连接。

        仅在首次 publish 时尝试连接 Redis，失败则置为 None（降级为单实例模式）。
        """
        if self._redis is not None:
            return self._redis
        try:
            import redis.asyncio as aioredis
            from app.config import settings

            redis_url = settings.REDIS_URL or "redis://localhost:6379/0"
            self._redis = aioredis.from_url(redis_url, decode_responses=True)
            await self._redis.ping()
            logger.info("WebSocket Redis pub/sub connected: %s", redis_url)
        except Exception:
            logger.warning("Redis 不可用，WebSocket 降级为单实例广播模式")
            self._redis = None
        return self._redis

    async def connect(self, conversation_id: int, websocket: WebSocket) -> None:
        """接受 WebSocket 握手，加入会话频道，并订阅 Redis 频道。

        参数：
            conversation_id: 会话 ID
            websocket: WebSocket 连接对象
        """
        await websocket.accept()
        self._connections[conversation_id].add(websocket)

    def connect_employee(self, employee_id: int) -> None:
        """记录员工有一条新 WebSocket 连接（用于在线状态判断）。"""
        self._employee_connections[employee_id] += 1

    def disconnect_employee(self, employee_id: int) -> bool:
        """记录员工断开一条连接。返回 True 表示该员工已无连接（变离线）。"""
        count = self._employee_connections.get(employee_id, 0)
        if count > 0:
            count -= 1
        self._employee_connections[employee_id] = count
        if count <= 0:
            self._employee_connections.pop(employee_id, None)
            return True
        return False

    def disconnect(self, conversation_id: int, websocket: WebSocket) -> None:
        """移除断开连接；频道为空时清理字典并退订 Redis。

        参数：
            conversation_id: 会话 ID
            websocket: 要移除的 WebSocket 连接
        """
        sockets = self._connections.get(conversation_id)
        if not sockets:
            return
        sockets.discard(websocket)
        if not sockets:
            self._connections.pop(conversation_id, None)

    async def broadcast(self, conversation_id: int, payload: dict[str, Any]) -> None:
        """向当前进程内订阅该会话的所有 WebSocket 发送事件。

        参数：
            conversation_id: 目标会话 ID
            payload: 要发送的 JSON 可序列化字典

        发送失败（连接已断开）的连接在当前轮广播结束后统一清理。
        """
        sockets = list(self._connections.get(conversation_id, set()))
        stale: list[WebSocket] = []
        for websocket in sockets:
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(conversation_id, websocket)

    async def publish(self, conversation_id: int, payload: dict[str, Any]) -> None:
        """跨实例发布消息。

        参数：
            conversation_id: 目标会话 ID
            payload: 消息负载（JSON 可序列化）

        执行逻辑：
            1. 先通过 Redis pub/sub 发布到频道（多实例扇出）
            2. 再写入本地连接（本实例直连的客户端）

        Redis 不可用时自动跳过步骤 1，降级为纯本地广播。
        本地广播（步骤 2）始终执行，确保本实例连接能收到消息。
        """
        # ── 步骤 1：Redis pub/sub 扇出 ──
        redis = await self._get_redis()
        if redis is not None:
            try:
                channel = f"fastagent:ws:{conversation_id}"
                # Snowflake ID 不可直接 JSON 序列化，手动处理
                await redis.publish(channel, json.dumps(payload, default=str))
            except Exception:
                logger.exception("Redis publish 失败，降级为本地广播")

        # ── 步骤 2：本地广播（始终执行） ──
        await self.broadcast(conversation_id, payload)

    async def start_redis_subscriber(self, conversation_id: int) -> None:
        """为该会话启动 Redis 频道订阅（从其他实例接收消息）。

        参数：
            conversation_id: 要订阅的会话 ID

        说明：
            - 每个 conversation_id 只订阅一次（_subscribed 去重）
            - 订阅在后台 asyncio Task 中运行，不阻塞主流程
            - 收到消息后反序列化并广播到本地 WebSocket 连接
            - Redis 不可用时静默跳过
        """
        if conversation_id in self._subscribed:
            return
        redis = await self._get_redis()
        if redis is None:
            return

        self._subscribed.add(conversation_id)
        channel = f"fastagent:ws:{conversation_id}"
        asyncio.create_task(self._listen_redis(channel, conversation_id))

    async def _listen_redis(self, channel: str, conversation_id: int) -> None:
        """后台任务：持续监听 Redis 频道，接收来自其他实例的消息并广播。

        参数：
            channel: Redis 频道名
            conversation_id: 对应的会话 ID（用于广播到本地连接）

        异常处理：
            - Redis 连接断开时自动重试（5 秒延迟）
            - 反序列化失败时记录警告但不崩溃
        """
        redis = self._redis
        if redis is None:
            return
        while True:
            try:
                pubsub = redis.pubsub()
                await pubsub.subscribe(channel)
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    try:
                        payload = json.loads(message["data"])
                        await self.broadcast(conversation_id, payload)
                    except (json.JSONDecodeError, TypeError):
                        logger.warning("Redis 消息反序列化失败: %s", message["data"][:200])
            except asyncio.CancelledError:
                await pubsub.unsubscribe(channel)
                break
            except Exception:
                logger.exception("Redis 订阅异常，5 秒后重试")
                await asyncio.sleep(5)

# 全局单例 — 由 ws.py 和 message_router/processor 等模块共享
manager = ConnectionManager()
