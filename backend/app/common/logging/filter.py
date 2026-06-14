"""日志 TraceIdFilter — 向 LogRecord 注入 trace_id 字段。"""

from __future__ import annotations

import logging

from app.common.trace.context import get_trace_id


class TraceIdFilter(logging.Filter):
    """向所有 LogRecord 注入 trace_id 属性。

    通过 logging.basicConfig 或 addFilter 注册到 root handler 后，
    日志格式可用 %(trace_id)s 引用该值。
    未设置 trace_id 时显示 "-"，避免 Formatter 报错。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id() or "-"
        return True
