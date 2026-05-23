"""WebSocket endpoints."""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import JWTError

from app.core.security import decode_token
from app.core.websocket_manager import manager
from app.database import AsyncSessionLocal
from app.models.employee import Employee
from app.schemas.conversation import MessageCreate
from app.services import conversation_service

router = APIRouter(tags=["WebSocket"])


def _message_payload(message) -> dict:
    """生成 WebSocket 消息事件的 payload。

    WebSocket 不走 FastAPI response_model，所以这里手动把 Snowflake ID 转成字符串，
    保持字段名和 REST API 的 MessageResponse/camelCase 输出一致。
    """
    return {
        "id": str(message.id),
        "conversationId": str(message.conversation_id),
        "senderType": message.sender_type,
        "contentType": message.content_type,
        "content": message.content,
        "metadata": message.metadata_ or {},
        "replyToId": str(message.reply_to_id) if message.reply_to_id else None,
        "isRead": message.is_read,
        "isRecalled": message.is_recalled,
        "createdAt": message.created_at.isoformat(),
    }


@router.websocket("/ws/{conversation_id}")
async def websocket_endpoint(websocket: WebSocket, conversation_id: int, token: str):
    """会话级 WebSocket 入口。

    连接流程：
    1. 使用 query token 做 JWT 鉴权。
    2. 校验员工存在、未删除，并且目标会话属于该员工所在租户。
    3. 加入 conversation_id 对应频道，之后该会话的新消息会实时广播到所有在线页面。

    消息流程：
    - 客户端发送 message.send 时，服务端写入 messages 表。
    - 写入成功后广播 message.created。
    - 真实客户入站和 AI 回复会在后续渠道/AI 管线中接入。
    """
    try:
        payload = decode_token(token)
        employee_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        await websocket.close(code=1008)
        return

    async with AsyncSessionLocal() as db:
        employee = await db.get(Employee, employee_id)
        if employee is None or employee.deleted_at is not None:
            await websocket.close(code=1008)
            return
        conversation = await conversation_service.get_conversation(
            db,
            conversation_id,
            employee.tenant_id,
        )
        if conversation is None:
            await websocket.close(code=1008)
            return

    await manager.connect(conversation_id, websocket)

    async def heartbeat() -> None:
        """服务端心跳。

        每 30 秒发送一次 ping，让前端能判断连接仍然活着，也方便代理层保持连接不被静默断开。
        """
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"type": "ping"})

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        await websocket.send_json({"type": "connected", "conversationId": str(conversation_id)})
        while True:
            data = await websocket.receive_json()
            message_type = data.get("type")
            if message_type == "pong":
                continue
            if message_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if message_type != "message.send":
                continue

            content = str(data.get("content") or "").strip()
            if not content:
                continue

            async with AsyncSessionLocal() as db:
                _, message = await conversation_service.create_message(
                    db,
                    conversation_id,
                    employee.tenant_id,
                    MessageCreate(
                        sender_type=str(data.get("senderType") or "AGENT"),
                        content_type=str(data.get("contentType") or "text"),
                        content=content,
                    ),
                )
                await manager.publish(
                    conversation_id,
                    {"type": "message.created", "message": _message_payload(message)},
                )
    except WebSocketDisconnect:
        pass
    finally:
        heartbeat_task.cancel()
        manager.disconnect(conversation_id, websocket)
