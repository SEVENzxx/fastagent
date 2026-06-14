"""FastAPI 中间件 — 在请求入口生成或继承 trace_id。

当前仅定义中间件函数，**未注册到 app/main.py**。
接入时在 app/main.py 中添加::

    from app.common.trace.middleware import TraceIdMiddleware
    app.add_middleware(TraceIdMiddleware)
"""

from __future__ import annotations

import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send

from app.common.trace.context import set_trace_id

_TRACE_ID_HEADER = "X-Trace-Id"


class TraceIdMiddleware:
    """从请求头读取或生成 trace_id，注入 ContextVar。

    同时将 trace_id 写入响应头，便于下游服务继承。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = MutableHeaders(scope=scope)
        tid = headers.get(_TRACE_ID_HEADER, "")

        if not tid:
            tid = uuid.uuid4().hex[:16]
        set_trace_id(tid)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append(_TRACE_ID_HEADER, tid)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            from app.common.trace.context import reset_trace_id
            reset_trace_id()
