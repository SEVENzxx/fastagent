"""会话消息缓冲：防抖合并 + 分布式锁，确保同一时间只有一个人在工作。

场景：客户在企微里连续发多条消息（如"在吗？帮我查个订单。
订单号是 20260608001"），如果不做缓冲，每条消息都会触发一次 AI 管线，
出现"并发错乱"——后一条处理到一半被前一条的结果覆盖。

本模块用一个 Redis list 缓存连续消息，等 1.5 秒没有新消息后，
才把缓存的消息合成一条交给 AI 管线处理。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# ── 默认配置 ──
# 防抖等待时间：最后一条消息后等多久才触发处理
DEFAULT_DEBOUNCE_SECONDS = 1.5
# 缓存消息的 Redis TTL：超时未处理则丢弃
DEFAULT_BUFFER_TTL_SECONDS = 60
# 分布式锁的超时时间：防止死锁
DEFAULT_LOCK_TTL_SECONDS = 45
# 等待获取锁的最长时间
DEFAULT_LOCK_WAIT_SECONDS = 30


class RedisLike(Protocol):
    """Redis 客户端的最小接口协议，便于单元测试注入 fake redis。"""
    async def get(self, name: str) -> Any: ...
    async def set(self, name: str, value: str, ex: int | None = None, nx: bool = False) -> Any: ...
    async def incr(self, name: str) -> Any: ...
    async def expire(self, name: str, time: int) -> Any: ...
    async def rpush(self, name: str, *values: str) -> Any: ...
    async def lrange(self, name: str, start: int, end: int) -> Any: ...
    async def delete(self, *names: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class BufferedMessageBatch:
    """缓存的一批消息：合并后的文本 + 原始消息 ID 列表。"""
    text: str                   # 多条消息用 \n 拼接后的完整文本
    message_ids: list[str]      # 原始消息 ID 列表（按发送顺序）
    message_count: int          # 消息条数


class ConversationMessageBuffer:
    """消息缓冲 + 防抖 + 分布式互斥锁。

    核心机制（版本号 + Redis SET NX 锁）：
      1. 每条消息入队后，递增 Redis 中的"版本号"
      2. 等待防抖时间（1.5s）后检查版本号是否变化
      3. 如果变了 → 说明又有新消息到达，放弃本次处理（由最新 worker 处理）
      4. 如果没变 → 尝试获取分布式锁（SET NX）
      5. 获取成功 → 从 buffer 中取出所有消息，清空 buffer 和版本号
      6. 获取失败 → 等待锁释放或超时

    这样保证：
      - 快速连续消息不会触发多次 AI 管线（防抖）
      - 不会有多个人同时处理同一条会话（分布式锁）
      - 先到的 worker 不会被后到的覆盖（版本号缓存）
    """

    def __init__(
        self,
        redis_client: RedisLike | None = None,
        *,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        buffer_ttl_seconds: int = DEFAULT_BUFFER_TTL_SECONDS,
        lock_ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
        lock_wait_seconds: float = DEFAULT_LOCK_WAIT_SECONDS,
    ) -> None:
        self.redis = redis_client or self._create_redis_client()
        self.debounce_seconds = float(debounce_seconds)
        self.buffer_ttl_seconds = int(buffer_ttl_seconds)
        self.lock_ttl_seconds = int(lock_ttl_seconds)
        self.lock_wait_seconds = float(lock_wait_seconds)
        self._held_lock_value: str | None = None  # 当前 worker 持有的锁值，释放时校验

    async def wait_for_batch(
        self,
        *,
        tenant_id: int,
        conversation_id: int,
        message_id: int,
        text: str,
    ) -> BufferedMessageBatch | None:
        """将一条消息追加到缓冲区，防抖后返回批处理结果。

        返回 None 表示当前 worker 已经过期（有新消息到达），
        由最新到达的那个 worker 负责处理这批消息。
        """
        text = text.strip()
        if not text:
            return None

        # ── 1: 消息入队 ──
        payload = json.dumps(
            {
                "message_id": str(message_id),
                "text": text,
                "received_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        buffer_key = self._buffer_key(tenant_id, conversation_id)
        version_key = self._version_key(tenant_id, conversation_id)
        lock_key = self._lock_key(tenant_id, conversation_id)

        await self.redis.rpush(buffer_key, payload)
        await self.redis.expire(buffer_key, self.buffer_ttl_seconds)
        version = int(await self.redis.incr(version_key))
        await self.redis.expire(version_key, self.buffer_ttl_seconds)
        logger.info(
            "[message_buffer] appended tenant=%s conversation=%s message=%s version=%s",
            tenant_id,
            conversation_id,
            message_id,
            version,
        )

        # ── 2: 防抖等待 ──
        await asyncio.sleep(self.debounce_seconds)

        # ── 3: 检查版本号 — 有更新的消息到达则放弃 ──
        if await self._current_version(version_key) != version:
            logger.info(
                "[message_buffer] stale worker skipped tenant=%s conversation=%s message=%s version=%s",
                tenant_id,
                conversation_id,
                message_id,
                version,
            )
            return None

        # ── 4: 竞争分布式锁 — 确保同一条会话不会多线处理 ──
        deadline = asyncio.get_running_loop().time() + self.lock_wait_seconds
        while True:
            lock_value = f"{message_id}:{version}"
            acquired = await self.redis.set(lock_key, lock_value, ex=self.lock_ttl_seconds, nx=True)
            if acquired:
                self._held_lock_value = lock_value
                # 获取锁后再检查一次版本号（锁等待期间可能有新消息）
                if await self._current_version(version_key) != version:
                    await self.release_lock(tenant_id, conversation_id)
                    return None
                return await self._drain_batch(buffer_key, version_key)

            # 锁已被其他 worker 持有 → 等待释放或超时
            if asyncio.get_running_loop().time() >= deadline:
                logger.warning(
                    "[message_buffer] lock wait timeout tenant=%s conversation=%s message=%s version=%s",
                    tenant_id,
                    conversation_id,
                    message_id,
                    version,
                )
                return None
            await asyncio.sleep(min(0.5, self.debounce_seconds))
            if await self._current_version(version_key) != version:
                return None

    async def release_lock(self, tenant_id: int, conversation_id: int) -> None:
        """安全释放分布式锁（只释放自己持有的锁，不误删别人的）。"""
        lock_key = self._lock_key(tenant_id, conversation_id)
        if self._held_lock_value is None:
            return
        current = await self.redis.get(lock_key)
        if isinstance(current, bytes):
            current = current.decode("utf-8")
        if current == self._held_lock_value:
            await self.redis.delete(lock_key)
        self._held_lock_value = None

    async def _drain_batch(self, buffer_key: str, version_key: str) -> BufferedMessageBatch:
        """从 buffer 中取出所有消息，清空 buffer 和版本号，返回合并的 batch。"""
        raw_items = await self.redis.lrange(buffer_key, 0, -1)
        await self.redis.delete(buffer_key, version_key)

        texts: list[str] = []
        message_ids: list[str] = []
        for raw in raw_items:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            try:
                item = json.loads(str(raw))
            except json.JSONDecodeError:
                continue
            text = str(item.get("text") or "").strip()
            if text:
                texts.append(text)
            message_id = str(item.get("message_id") or "").strip()
            if message_id:
                message_ids.append(message_id)

        batch = BufferedMessageBatch(
            text="\n".join(texts),
            message_ids=message_ids,
            message_count=len(message_ids),
        )
        logger.info(
            "[message_buffer] drained batch count=%s message_ids=%s text_len=%s",
            batch.message_count,
            batch.message_ids,
            len(batch.text),
        )
        return batch

    async def _current_version(self, version_key: str) -> int | None:
        """读取当前版本号（用于判断是否有新消息到达）。"""
        raw = await self.redis.get(version_key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def _buffer_key(self, tenant_id: int, conversation_id: int) -> str:
        """Redis key：消息缓冲区（List）。"""
        return f"conversation:{tenant_id}:{conversation_id}:incoming_buffer"

    def _version_key(self, tenant_id: int, conversation_id: int) -> str:
        """Redis key：版本号（递增计数器）。"""
        return f"conversation:{tenant_id}:{conversation_id}:incoming_buffer_version"

    def _lock_key(self, tenant_id: int, conversation_id: int) -> str:
        """Redis key：分布式锁（SET NX）。"""
        return f"conversation:{tenant_id}:{conversation_id}:ai_lock"

    def _create_redis_client(self) -> RedisLike:
        """懒加载真实 Redis 客户端（避免测试环境 import 报错）。"""
        from app.integrations.redis_client import get_redis_client
        return get_redis_client()
