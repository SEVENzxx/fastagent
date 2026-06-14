"""会话状态持久化 — 单模型 SessionContext 贯穿所有层。

SessionContext (Pydantic) ←→ Redis JSON
通过 Pydantic model_dump / model_validate 直接序列化，不需要转换桥。

Redis client 使用模块级缓存，避免高频调用时重复创建连接。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Protocol

from app.ai.context.session_context import SessionContext
from app.ai.observability import observe_db_call, set_observation_io

DEFAULT_CONVERSATION_STATE_TTL_SECONDS = 3600

# 模块级 Redis client 缓存，避免每次 ConversationStateStore() 新建连接
_redis_client: Any | None = None


class RedisLike(Protocol):
    """Redis 客户端的最小接口协议，便于单元测试注入 fake redis。"""
    async def get(self, name: str) -> Any: ...
    async def set(self, name: str, value: str, ex: int | None = None) -> Any: ...
    async def delete(self, *names: str) -> Any: ...


def _get_redis_client() -> RedisLike:
    """获取模块级缓存的 Redis 客户端。

    首次调用时创建，后续复用同一连接池。
    """
    global _redis_client
    if _redis_client is None:
        from app.redis_client import get_redis_client
        _redis_client = get_redis_client()
    return _redis_client


async def close_cached_redis_client() -> None:
    """关闭模块级缓存的 Redis 连接（应用 shutdown 时调用）。"""
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except Exception:
            pass
        _redis_client = None


class ConversationStateStore:
    """会话状态的 Redis 持久化存储。

    直接读/写 SessionContext，用 Pydantic model_validate / model_dump 做序列化。
    key 格式：conversation:{tenant_id}:{conversation_id}:session
    """

    def __init__(
        self,
        redis_client: RedisLike | None = None,
        *,
        ttl_seconds: int = DEFAULT_CONVERSATION_STATE_TTL_SECONDS,
    ) -> None:
        self.redis = redis_client or _get_redis_client()
        self.ttl_seconds = int(ttl_seconds)
        if self.ttl_seconds <= 0:
            raise ValueError("TTL 必须大于 0")

    async def get(self, tenant_id: int, conversation_id: int) -> SessionContext:
        """读取会话状态；不存在或解析失败时返回空的 SessionContext。"""
        key = self._key(tenant_id, conversation_id)
        async with observe_db_call(
            "redis",
            "get",
            tenant_id=tenant_id,
            input_data={"key": key, "tenant_id": tenant_id, "conversation_id": conversation_id},
        ) as observation:
            raw = await self.redis.get(key)
            raw_len = len(raw) if isinstance(raw, (bytes, str)) else 0
            set_observation_io(observation, output_data={"hit": raw is not None, "bytes": raw_len})
        if raw is None:
            return SessionContext(tenant_id=tenant_id, conversation_id=conversation_id)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            data = json.loads(str(raw))
        except json.JSONDecodeError:
            return SessionContext(tenant_id=tenant_id, conversation_id=conversation_id)
        if not isinstance(data, dict):
            return SessionContext(tenant_id=tenant_id, conversation_id=conversation_id)
        return SessionContext.model_validate(data)

    async def set(
        self,
        tenant_id: int,
        conversation_id: int,
        state: SessionContext,
    ) -> None:
        """保存会话状态到 Redis，同时刷新 TTL。"""
        state.updated_at = datetime.now(timezone.utc).isoformat()
        payload = state.model_dump()
        key = self._key(tenant_id, conversation_id)
        async with observe_db_call(
            "redis",
            "set",
            tenant_id=tenant_id,
            input_data={
                "key": key,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "ttl_seconds": self.ttl_seconds,
                "payload_keys": sorted(str(key) for key in payload.keys()),
            },
        ) as observation:
            await self.redis.set(
                key,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                ex=self.ttl_seconds,
            )
            set_observation_io(observation, output_data={"ok": True, "ttl_seconds": self.ttl_seconds})

    async def delete(self, tenant_id: int, conversation_id: int) -> None:
        """删除会话状态（会话结束或重置时调用）。"""
        await self.redis.delete(self._key(tenant_id, conversation_id))

    def _key(self, tenant_id: int, conversation_id: int) -> str:
        return f"conversation:{tenant_id}:{conversation_id}:session"
