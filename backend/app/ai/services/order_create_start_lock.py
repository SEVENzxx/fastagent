"""下单创建入口短锁服务。

用于拦截同一会话内几乎同时进入的多个下单图线程创建请求。
"""

from __future__ import annotations

import hashlib

from app.ai.context.session_context import SessionContext
from app.ai.services.idempotency import order_idempotency

_ORDER_CREATE_START_LOCK_TTL_SECONDS = 10
_ORDER_CREATE_START_LOCK_SALT = "order_create_start_v1"


class OrderCreateStartLock:
    """下单创建入口短锁。"""

    def __init__(self, ttl_seconds: int = _ORDER_CREATE_START_LOCK_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds

    @staticmethod
    def _build_key(ctx: SessionContext) -> str:
        """按会话维度生成短锁 key。"""
        raw = "|".join([
            _ORDER_CREATE_START_LOCK_SALT,
            str(ctx.tenant_id),
            str(ctx.conversation_id),
            str(ctx.contact_id or ""),
        ])
        return f"start:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"

    async def acquire(self, ctx: SessionContext, text: str) -> bool:
        """尝试获取下单入口短锁，成功返回 True。"""
        return await order_idempotency.setnx(
            self._build_key(ctx),
            {"status": "processing", "text": text[:100]},
            ttl=self._ttl_seconds,
        )


order_create_start_lock = OrderCreateStartLock()
