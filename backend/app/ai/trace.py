"""ResourceTrace 跨层传播 — contextvar 实现。

Gateway 层（LLMGateway / VectorGateway）通过 get_trace() 读取当前协程的追踪字典，
自动记录 llm_calls / vector_calls，Handler 无需手动计数。

用法:
    from app.ai.trace import get_trace, inc_llm, inc_vector

    trace = get_trace()
    if trace is not None:
        inc_llm(trace)   # trace["llm_calls"] += 1
        inc_vector(trace)  # trace["vector_calls"] += 1
"""

from __future__ import annotations

import contextvars
from typing import Any

TraceDict = dict[str, Any]

_trace_ctx: contextvars.ContextVar[TraceDict | None] = contextvars.ContextVar(
    "resource_trace", default=None,
)


def get_trace() -> TraceDict | None:
    """获取当前协程的追踪字典。"""
    return _trace_ctx.get()


def set_trace(td: TraceDict | None) -> None:
    """设置当前协程的追踪字典。"""
    _trace_ctx.set(td)


def inc_llm(td: TraceDict) -> None:
    """递增 llm_calls。"""
    td["llm_calls"] = td.get("llm_calls", 0) + 1


def inc_vector(td: TraceDict) -> None:
    """递增 vector_calls。"""
    td["vector_calls"] = td.get("vector_calls", 0) + 1


def add_skill_call(td: TraceDict, name: str) -> None:
    """追加一条 skill_calls。"""
    td.setdefault("skill_calls", []).append(name)
