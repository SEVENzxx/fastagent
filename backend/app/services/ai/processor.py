"""AI 入站消息处理编排。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.websocket_manager import manager
from app.models.conversation import Conversation, Message
from app.schemas.conversation import ConversationUpdate, MessageCreate
from app.services import conversation_service, outbound_message_service
from app.services.ai.intent.pending_state_store import PendingStateStore
from app.services.ai.intent.pipeline import IntentRecognitionPipeline
from app.services.ai.message_router import MessageRouter


def message_payload(message: Message) -> dict:
    """生成 WebSocket 消息事件 payload。"""
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


def conversation_payload(conversation: Conversation) -> dict:
    """生成会话更新事件 payload。"""
    return {
        "id": str(conversation.id),
        "tenantId": str(conversation.tenant_id),
        "contactId": str(conversation.contact_id),
        "employeeId": str(conversation.employee_id) if conversation.employee_id else None,
        "platformId": str(conversation.platform_id) if conversation.platform_id else None,
        "status": conversation.status,
        "handlingType": conversation.handling_type,
        "isTransferred": conversation.is_transferred,
        "transferReason": conversation.transfer_reason,
        "tags": conversation.tags or [],
        "lastMessageAt": conversation.last_message_at.isoformat() if conversation.last_message_at else None,
        "idleTimeoutSeconds": conversation.idle_timeout_seconds,
        "createdAt": conversation.created_at.isoformat(),
        "closedAt": conversation.closed_at.isoformat() if conversation.closed_at else None,
    }


async def process_customer_message_with_ai(
    db: AsyncSession,
    conversation: Conversation,
    customer_message: Message,
) -> None:
    """对客户入站消息执行 AI 识别、路由和回复。

    当前 Phase 8 先打通核心链路：
    - HUMAN：更新会话为待人工，并落一条 SYSTEM 提示。
    - SILENT：不回复。
    - GENERAL_REPLY/AGENT：生成 AI 文本，落库、广播，并尝试出站到企业微信。
    """
    if conversation.status in {"closed", "human_processing", "pending_human"}:
        return
    if conversation.handling_type == "human":
        return
    if customer_message.sender_type != "CUSTOMER" or customer_message.content_type != "text":
        return

    pending_store = PendingStateStore()
    pending_state = await pending_store.get(conversation.tenant_id, conversation.id)
    result = await IntentRecognitionPipeline().recognize_and_route(
        customer_message.content or "",
        pending_state=pending_state,
    )

    await manager.publish(
        conversation.id,
        {
            "type": "ai.routed",
            "route": result.route,
            "skill": result.skill,
            "primaryIntent": result.primary_intent,
            "confidence": result.confidence,
            "needClarification": result.need_clarification,
        },
    )

    if result.route == "SILENT":
        return

    if result.route == "HUMAN":
        await pending_store.delete(conversation.tenant_id, conversation.id)
        await _mark_pending_human(db, conversation, result.reason or result.primary_intent or "需要人工处理")
        await _create_and_broadcast_system_message(
            db,
            conversation,
            "您已接入人工客服，请稍候，客服人员将尽快为您服务。",
            metadata={"ai_route": "HUMAN", "intent": result.primary_intent},
        )
        return

    # 首次 AI 对话时，发送系统提示告知客户
    if "ai_greeting_sent" not in (conversation.tags or []):
        await _create_and_broadcast_system_message(
            db,
            conversation,
            "您好，我是 AI 智能助手，正在为您服务。如需人工客服，请随时告知。",
            metadata={"type": "ai_greeting"},
        )
        conversation.tags = (conversation.tags or []) + ["ai_greeting_sent"]

    router = MessageRouter()
    if result.route == "GENERAL_REPLY":
        await _publish_typing(conversation, True)
        chunks: list[str] = []
        try:
            async for chunk in router.dispatch_stream(result):
                chunks.append(chunk)
                await manager.publish(conversation.id, {"type": "ai.message.chunk", "content": chunk})
        finally:
            await _publish_typing(conversation, False)
        content = "".join(chunks).strip()
    else:
        routed_result = await router.dispatch(result)
        content = routed_result.message.strip()

    if not content:
        return

    await _create_deliver_and_broadcast_ai_message(
        db,
        conversation,
        content,
        metadata={
            "ai_route": result.route,
            "skill": result.skill,
            "intent": result.primary_intent,
            "confidence": result.confidence,
            "is_multi_intent": result.is_multi_intent,
        },
    )


async def _mark_pending_human(db: AsyncSession, conversation: Conversation, reason: str) -> None:
    updated = await conversation_service.update_conversation(
        db,
        conversation.id,
        conversation.tenant_id,
        ConversationUpdate(
            status="pending_human",
            handling_type="human",
            is_transferred=True,
            transfer_reason=reason,
        ),
    )
    if updated is not None:
        await manager.publish(
            conversation.id,
            {"type": "conversation.updated", "conversation": conversation_payload(updated)},
        )


async def _create_and_broadcast_system_message(
    db: AsyncSession,
    conversation: Conversation,
    content: str,
    *,
    metadata: dict,
) -> None:
    _, message = await conversation_service.create_message(
        db,
        conversation.id,
        conversation.tenant_id,
        MessageCreate(sender_type="SYSTEM", content_type="text", content=content, metadata=metadata),
    )
    message = await outbound_message_service.deliver_message(db, conversation, message)
    await manager.publish(conversation.id, {"type": "message.created", "message": message_payload(message)})


async def _create_deliver_and_broadcast_ai_message(
    db: AsyncSession,
    conversation: Conversation,
    content: str,
    *,
    metadata: dict,
) -> None:
    conversation, message = await conversation_service.create_message(
        db,
        conversation.id,
        conversation.tenant_id,
        MessageCreate(sender_type="AI", content_type="text", content=content, metadata=metadata),
    )
    message = await outbound_message_service.deliver_message(db, conversation, message)
    await manager.publish(conversation.id, {"type": "message.created", "message": message_payload(message)})


async def _publish_typing(conversation: Conversation, typing: bool) -> None:
    await manager.publish(
        conversation.id,
        {
            "type": "ai.typing",
            "typing": typing,
            "conversationId": str(conversation.id),
        },
    )
