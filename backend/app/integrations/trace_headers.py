"""Trace ID 透传工具 — 为外部 HTTP 请求注入 X-Trace-Id 请求头。"""

from __future__ import annotations

from app.common.trace.context import get_trace_id

TRACE_HEADER_NAME = "X-Trace-Id"


def inject_trace_header(headers: dict | None) -> dict:
    """若 get_trace_id() 非空且 headers 中尚无 X-Trace-Id（大小写不敏感），注入该请求头。

    始终返回新 dict，不修改入参。
    若原 headers 中存在任意大小写变体的 X-Trace-Id，保持原样返回，不注入、不覆盖。
    """
    result = dict(headers) if headers is not None else {}
    tid = get_trace_id()
    if tid:
        header_lower = TRACE_HEADER_NAME.lower()
        has_trace = any(k.lower() == header_lower for k in result)
        if not has_trace:
            result[TRACE_HEADER_NAME] = tid
    return result
