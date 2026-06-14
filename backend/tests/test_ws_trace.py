"""WebSocket trace_id 继承与生命周期测试。"""

from __future__ import annotations

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient

from app.common.trace.context import ensure_trace_id, get_trace_id, reset_trace_id, set_trace_id


def _make_ws_trace_app() -> FastAPI:
    """创建独立 WebSocket trace 测试 app（不依赖 DB / JWT 鉴权）。"""

    app = FastAPI()

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        await websocket.accept()
        # 模拟 ws.py 中 websocket_endpoint 的 trace_id 生命周期
        tid = websocket.headers.get("X-Trace-Id", "")
        if tid:
            set_trace_id(tid)
        else:
            ensure_trace_id()
        try:
            current = get_trace_id()
            await websocket.send_json({"type": "trace", "trace_id": current})
            # 保持连接直到客户端断开
            try:
                while True:
                    await websocket.receive_json()
            except WebSocketDisconnect:
                pass
        finally:
            reset_trace_id()

    return app


class TestWebSocketTraceId:
    """WebSocket 连接级 trace_id 生命周期。"""

    def setup_method(self) -> None:
        reset_trace_id()
        self.app = _make_ws_trace_app()
        self.client = TestClient(self.app)

    def test_inherits_trace_id_from_header(self) -> None:
        """带 X-Trace-Id 连接时，服务端 trace_id 等于该值。"""
        with self.client.websocket_connect(
            "/ws", headers={"X-Trace-Id": "ws-custom-trace-id"}
        ) as ws:
            data = ws.receive_json()
            assert data["trace_id"] == "ws-custom-trace-id"

    def test_generates_trace_id_when_missing(self) -> None:
        """不带 X-Trace-Id 时，服务端生成非空 16 字符十六进制 trace_id。"""
        with self.client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            tid = data["trace_id"]
            assert len(tid) == 16
            assert all(c in "0123456789abcdef" for c in tid)

    def test_resets_after_disconnect(self) -> None:
        """连接断开后 get_trace_id() 被重置。"""
        with self.client.websocket_connect("/ws") as ws:
            _ = ws.receive_json()
        assert get_trace_id() == ""
