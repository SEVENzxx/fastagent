"""trace_id 中间件 & 日志 Filter & BackgroundTasks 继承测试。"""

from __future__ import annotations

import logging

from fastapi import BackgroundTasks, FastAPI
from fastapi.testclient import TestClient

from app.common.logging.filter import TraceIdFilter
from app.common.trace.context import get_trace_id, reset_trace_id, set_trace_id
from app.common.trace.middleware import TraceIdMiddleware


# ═══════════════════════════════════════════════════════════════════════
# TraceIdFilter 测试
# ═══════════════════════════════════════════════════════════════════════


class TestTraceIdFilter:
    """TraceIdFilter 向 LogRecord 注入 trace_id 字段。"""

    def setup_method(self) -> None:
        reset_trace_id()
        self.filter = TraceIdFilter()
        self.logger = logging.getLogger(__name__)

    def test_no_trace_id_uses_dash(self) -> None:
        """未设置 trace_id 时 record.trace_id == '-'。"""
        record = self.logger.makeRecord(
            self.logger.name, logging.INFO, "", 0, "test", (), None,
        )
        assert self.filter.filter(record)
        assert record.trace_id == "-"

    def test_with_trace_id(self) -> None:
        """设置 trace_id 后 record.trace_id 为对应值。"""
        set_trace_id("abc123")
        record = self.logger.makeRecord(
            self.logger.name, logging.INFO, "", 0, "test", (), None,
        )
        assert self.filter.filter(record)
        assert record.trace_id == "abc123"

    def test_empty_trace_id_uses_dash(self) -> None:
        """trace_id 为空字符串时显示 '-','''"""
        set_trace_id("")
        record = self.logger.makeRecord(
            self.logger.name, logging.INFO, "", 0, "test", (), None,
        )
        assert self.filter.filter(record)
        assert record.trace_id == "-"


# ═══════════════════════════════════════════════════════════════════════
# TraceIdMiddleware 测试
# ═══════════════════════════════════════════════════════════════════════


def _make_test_app() -> FastAPI:
    """创建独立测试 app（不依赖 main.py，避免 DB 等副作用）。"""
    app_ = FastAPI()

    @app_.get("/test")
    async def test_endpoint():
        return {"trace_id": get_trace_id()}

    app_.add_middleware(TraceIdMiddleware)
    return app_


class TestTraceIdMiddleware:
    """TraceIdMiddleware 自动生成/继承 X-Trace-Id。"""

    def setup_method(self) -> None:
        reset_trace_id()
        self.app = _make_test_app()
        self.client = TestClient(self.app)

    def test_generates_trace_id_when_missing(self) -> None:
        """无 X-Trace-Id 请求头时，响应头自动生成 16 字符十六进制 trace_id。"""
        resp = self.client.get("/test")
        tid = resp.headers.get("X-Trace-Id")
        assert tid is not None, "响应头应包含 X-Trace-Id"
        assert len(tid) == 16
        assert all(c in "0123456789abcdef" for c in tid)

    def test_inherits_trace_id_from_request(self) -> None:
        """请求携带 X-Trace-Id 时，响应头继承该值。"""
        resp = self.client.get("/test", headers={"X-Trace-Id": "my-custom-trace-id"})
        assert resp.headers.get("X-Trace-Id") == "my-custom-trace-id"

    def test_trace_id_in_context(self) -> None:
        """请求处理过程中 ContextVar 可读取到 trace_id。"""
        resp = self.client.get("/test")
        body = resp.json()
        tid_header = resp.headers.get("X-Trace-Id")
        assert body["trace_id"] == tid_header

    def test_resets_after_request(self) -> None:
        """请求结束后 ContextVar 被重置为空。"""
        _ = self.client.get("/test")
        assert get_trace_id() == ""

    def test_trace_id_length_and_format(self) -> None:
        """自动生成的 trace_id 为 16 字符十六进制。"""
        resp = self.client.get("/test")
        tid = resp.headers.get("X-Trace-Id")
        assert len(tid) == 16
        assert tid.isalnum()

    def test_multiple_requests_get_different_ids(self) -> None:
        """多次请求获取不同的 trace_id。"""
        ids = set()
        for _ in range(5):
            resp = self.client.get("/test")
            ids.add(resp.headers.get("X-Trace-Id"))
        assert len(ids) == 5


# ═══════════════════════════════════════════════════════════════════════
# BackgroundTasks trace_id 继承测试
# ═══════════════════════════════════════════════════════════════════════


def _make_background_app(results: list) -> FastAPI:
    """创建含 BackgroundTasks 的测试 app。"""

    async def _capture_trace_id() -> None:
        """后台任务：记录当前 trace_id。"""
        results.append(get_trace_id())

    app_ = FastAPI()

    @app_.get("/test")
    async def test_endpoint(background_tasks: BackgroundTasks):
        background_tasks.add_task(_capture_trace_id)
        return {"trace_id": get_trace_id()}

    app_.add_middleware(TraceIdMiddleware)
    return app_


class TestBackgroundTasksTraceId:
    """BackgroundTasks 是否能继承请求的 trace_id。"""

    def setup_method(self) -> None:
        reset_trace_id()
        self.results: list[str] = []
        self.app = _make_background_app(self.results)
        self.client = TestClient(self.app)

    def test_background_inherits_auto_generated(self) -> None:
        """无 X-Trace-Id 请求，后台任务读到自动生成的 trace_id。"""
        resp = self.client.get("/test")
        assert len(self.results) == 1
        tid_header = resp.headers.get("X-Trace-Id")
        assert self.results[0] == tid_header, "后台任务应继承请求的 trace_id"

    def test_background_inherits_custom_header(self) -> None:
        """携带 X-Trace-Id 请求，后台任务读到传入的 trace_id。"""
        resp = self.client.get("/test", headers={"X-Trace-Id": "bg-task-inherit"})
        assert len(self.results) == 1
        assert self.results[0] == "bg-task-inherit"

    def test_resets_after_request(self) -> None:
        """请求及 BackgroundTasks 完成后，ContextVar 被重置。"""
        self.client.get("/test")
        # BackgroundTasks 已执行完毕，ContextVar 应在 finally 块中被重置
        assert get_trace_id() == ""
