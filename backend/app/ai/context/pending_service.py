"""PendingService — LangGraph Pending 状态的 Redis 独立存储。

key 格式：pending:{tenant_id}:{conversation_id}
与 SessionContext 分开存储；Pending TTL 固定为图恢复窗口。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.ai.context.pending_state import PendingDirective, PendingState, PendingStateCorruptedError
from app.common.constants.config import GRAPH_PENDING_TTL_SECONDS

logger = logging.getLogger(__name__)

# 模块级 Redis client 缓存
_redis_client: Any | None = None


def _get_redis_client() -> Any:
    global _redis_client
    if _redis_client is None:
        from app.integrations.redis_client import get_redis_client
        _redis_client = get_redis_client()
    return _redis_client


async def close_cached_pending_redis_client() -> None:
    """关闭模块级缓存的 Redis 连接（应用 shutdown 时调用）。"""
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except Exception:
            logger.warning("关闭 PendingService Redis 连接失败")
        _redis_client = None


class PendingService:
    """LangGraph Pending 状态读写，独立 Redis key。"""

    def __init__(
        self,
        redis_client: Any | None = None,
        *,
        ttl_seconds: int = GRAPH_PENDING_TTL_SECONDS,
    ) -> None:
        self.redis = redis_client or _get_redis_client()
        self.ttl_seconds = ttl_seconds

    async def get(self, tenant_id: int, conversation_id: int) -> PendingState | None:
        """读取 Pending 状态。

        Returns:
            PendingState 或 None（key 不存在时）

        Raises:
            PendingStateCorruptedError: 数据损坏或解析失败
        """
        raw = await self.redis.get(self._key(tenant_id, conversation_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            data = json.loads(str(raw))
            return PendingState.model_validate(data)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.error(
                "Pending 数据损坏 tenant=%s conversation=%s error=%s raw=%.200s",
                tenant_id, conversation_id, exc, str(raw),
            )
            raise PendingStateCorruptedError(
                f"Pending 数据损坏 tenant={tenant_id} conversation={conversation_id}"
            ) from exc

    async def set(self, tenant_id: int, conversation_id: int, state: PendingState) -> None:
        """写入 Pending 状态。"""
        payload = state.model_dump(mode="json")
        await self.redis.set(
            self._key(tenant_id, conversation_id),
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            ex=self.ttl_seconds,
        )

    async def clear(self, tenant_id: int, conversation_id: int) -> None:
        """删除 Pending 状态。"""
        await self.redis.delete(self._key(tenant_id, conversation_id))

    async def apply_directive(
        self,
        *,
        tenant_id: int,
        conversation_id: int,
        directive: PendingDirective,
        pending_state: PendingState | None = None,
    ) -> None:
        """按指令执行 Pending 操作。

        Raises:
            ValueError: SET 指令但 pending_state 为 None
        """
        if directive == PendingDirective.SET:
            if pending_state is None:
                raise ValueError("SET 指令必须提供 pending_state")
            await self.set(tenant_id, conversation_id, pending_state)
        elif directive == PendingDirective.CLEAR:
            await self.clear(tenant_id, conversation_id)
        # KEEP: 不做任何操作

    @staticmethod
    def _key(tenant_id: int, conversation_id: int) -> str:
        return f"pending:{tenant_id}:{conversation_id}"