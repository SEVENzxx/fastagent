"""trace_id 上下文 — 用于跨调用链追踪请求。

基于 ContextVar 实现，不依赖任何框架。
API 中间件在请求入口生成 trace_id，各层通过 get_trace_id() 读取。
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


def get_trace_id() -> str:
    """获取当前请求的 trace_id。"""
    return _trace_id_var.get()


def set_trace_id(tid: str) -> str:
    """设置当前请求的 trace_id，返回设置的值。"""
    _trace_id_var.set(tid)
    return tid


def reset_trace_id() -> None:
    """重置当前请求的 trace_id 为空。"""
    _trace_id_var.set("")


def ensure_trace_id() -> str:
    """获取 trace_id，为空时自动生成新的 UUID 并返回。"""
    tid = _trace_id_var.get()
    if not tid:
        tid = uuid.uuid4().hex[:16]
        _trace_id_var.set(tid)
    return tid
