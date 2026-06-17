"""LangGraph 子图共享工具。

收敛三个子图（order_creation / order_cancel / order_refund）中重复的
异常处理和失败回复模式。
"""

from __future__ import annotations

import asyncio
from typing import Any


# ── 共享回复文案 ──


INVALID_CHOICE_REPLY = "无效的选择，请重新选择。"
CONFIRM_OR_CANCEL_PROMPT = "请回复「确认」或「取消」。"
SYSTEM_ERROR_REPLY = "系统异常，请稍后再试。"


# ── 失败/异常统一处理 ──


def graph_failed(
    operation: str,
    idempotency_key: str = "",
    error: str | None = None,
) -> dict[str, Any]:
    """图写操作失败，释放幂等占位并返回统一格式的错误 dict。"""
    if idempotency_key:
        from app.ai.services.idempotency import order_idempotency

        asyncio.ensure_future(order_idempotency.delete(idempotency_key))
    return {
        "error": error or f"{operation}失败，请稍后再试。",
        "reply": f"{operation}失败：{error or '请稍后再试。'}",
        "write_executed": True,
    }


def graph_exception(
    error: Exception,
    idempotency_key: str = "",
) -> dict[str, Any]:
    """图写操作异常，清理幂等占位并返回统一格式的错误 dict。"""
    if idempotency_key:
        from app.ai.services.idempotency import order_idempotency

        asyncio.ensure_future(order_idempotency.delete(idempotency_key))
    return {
        "error": str(error),
        "reply": SYSTEM_ERROR_REPLY,
        "write_executed": True,
    }
