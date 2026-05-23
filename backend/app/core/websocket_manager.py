"""WebSocket connection manager with a small Redis pub/sub abstraction hook."""

from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    """按 conversation_id 管理 WebSocket 连接。

    publish() 方法保留了 Redis pub/sub 的抽象入口，后续多 worker/多实例部署时可在这里接 Redis。
    """

    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, conversation_id: int, websocket: WebSocket) -> None:
        """接受 WebSocket 握手，并把连接加入对应会话频道。"""
        await websocket.accept()
        self._connections[conversation_id].add(websocket)

    def disconnect(self, conversation_id: int, websocket: WebSocket) -> None:
        """移除断开的连接；频道为空时清理字典，避免长期持有空集合。"""
        sockets = self._connections.get(conversation_id)
        if not sockets:
            return
        sockets.discard(websocket)
        if not sockets:
            self._connections.pop(conversation_id, None)

    async def broadcast(self, conversation_id: int, payload: dict[str, Any]) -> None:
        """把事件发送给当前进程内订阅该会话的所有 WebSocket。

        如果发送失败，说明连接已经不可用，会在本轮广播后统一清理。
        """
        sockets = list(self._connections.get(conversation_id, set()))
        stale: list[WebSocket] = []
        for websocket in sockets:
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(conversation_id, websocket)

    async def publish(self, conversation_id: int, payload: dict[str, Any]) -> None:
        """Publish message locally.

        TODO: Replace this with Redis pub/sub fan-out when multiple API workers are used.
        """
        await self.broadcast(conversation_id, payload)


manager = ConnectionManager()
