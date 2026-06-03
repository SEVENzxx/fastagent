"""PendingIntentState 的 Redis 存储封装。"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Protocol

from app.ai.classifier.types import PendingIntentState


DEFAULT_PENDING_STATE_TTL_SECONDS = 600


class RedisLike(Protocol):
    """PendingStateStore 需要的最小 Redis 接口，便于单元测试注入 fake。"""

    async def get(self, name: str) -> Any: ...

    async def set(self, name: str, value: str, ex: int | None = None) -> Any: ...

    async def delete(self, *names: str) -> Any: ...

    async def ttl(self, name: str) -> int: ...


class PendingStateStore:
    """会话 pending intent 状态存储。

    Redis key:
      conversation:{tenant_id}:{conversation_id}:pending_state

    设计约束：
    - pending state 是短生命周期状态，默认 TTL 10 分钟。
    - 状态只保存“当前等待什么槽位”，不保存完整对话历史。
    - 强规则命中 HUMAN 后，调用方应 delete()，避免旧任务继续影响会话。
    """

    def __init__(
        self,
        redis_client: RedisLike | None = None,
        *,
        ttl_seconds: int = DEFAULT_PENDING_STATE_TTL_SECONDS,
    ) -> None:
        self.redis = redis_client or self._create_redis_client()
        self.ttl_seconds = int(ttl_seconds)
        if self.ttl_seconds <= 0:
            raise ValueError("ttl_seconds 必须大于 0")

    async def get(self, tenant_id: int, conversation_id: int) -> PendingIntentState | None:
        """读取 pending state；不存在或 JSON 异常时返回 None。"""
        raw = await self.redis.get(self._key(tenant_id, conversation_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            data = json.loads(str(raw))
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        return self._from_dict(data)

    async def set(
        self,
        tenant_id: int,
        conversation_id: int,
        state: PendingIntentState,
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        """保存 pending state，并设置 TTL。"""
        payload = asdict(state)
        if not payload.get("created_at"):
            payload["created_at"] = datetime.now(timezone.utc).isoformat()
        await self.redis.set(
            self._key(tenant_id, conversation_id),
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            ex=int(ttl_seconds or self.ttl_seconds),
        )

    async def delete(self, tenant_id: int, conversation_id: int) -> None:
        """删除 pending state。"""
        await self.redis.delete(self._key(tenant_id, conversation_id))

    async def ttl(self, tenant_id: int, conversation_id: int) -> int:
        """返回 Redis TTL，便于调试和测试。"""
        return int(await self.redis.ttl(self._key(tenant_id, conversation_id)))

    def _key(self, tenant_id: int, conversation_id: int) -> str:
        """生成租户隔离的 Redis key。"""
        return f"conversation:{tenant_id}:{conversation_id}:pending_state"

    def _create_redis_client(self) -> RedisLike:
        """懒加载真实 Redis 客户端。

        单元测试注入 fake redis 时不会导入 redis 包，避免测试环境缺依赖导致 import 失败。
        """
        from app.redis_client import get_redis_client

        return get_redis_client()

    def _from_dict(self, data: dict[str, Any]) -> PendingIntentState | None:
        try:
            return PendingIntentState(
                intent=str(data["intent"]),
                skill=str(data["skill"]) if data.get("skill") is not None else None,
                required_entities=[str(item) for item in data.get("required_entities", [])],
                filled_entities={
                    str(key): str(value)
                    for key, value in dict(data.get("filled_entities", {})).items()
                },
                last_prompt=str(data["last_prompt"]) if data.get("last_prompt") is not None else None,
                created_at=str(data["created_at"]) if data.get("created_at") is not None else None,
            )
        except (KeyError, TypeError, ValueError):
            return None
