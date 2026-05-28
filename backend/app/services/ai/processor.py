"""AI 入站消息处理编排。"""

from __future__ import annotations

import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.websocket_manager import manager
from app.models.conversation import Conversation, Message
from app.schemas.conversation import ConversationUpdate, MessageCreate
from app.services import conversation_service, outbound_message_service
from app.services.ai.intent.pending_state_store import PendingStateStore
from app.services.ai.intent.pipeline import IntentRecognitionPipeline
from app.services.ai.message_router import MessageRouter
from app.services.ai.agent.types import AgentContext

logger = logging.getLogger(__name__)


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
        logger.info(
            "跳过 AI 处理：conversation_id=%s status=%s",
            conversation.id,
            conversation.status,
        )
        return
    if conversation.handling_type == "human":
        logger.info(
            "跳过 AI 处理：conversation_id=%s 已由人工接待",
            conversation.id,
        )
        return
    if customer_message.sender_type != "CUSTOMER" or customer_message.content_type != "text":
        logger.info(
            "跳过 AI 处理：message_id=%s sender_type=%s content_type=%s",
            customer_message.id,
            customer_message.sender_type,
            customer_message.content_type,
        )
        return

    started = time.perf_counter()
    logger.info(
        "开始 AI 处理：tenant_id=%s conversation_id=%s message_id=%s content_len=%s",
        conversation.tenant_id,
        conversation.id,
        customer_message.id,
        len(customer_message.content or ""),
    )
    pending_store = PendingStateStore()
    pending_state = await pending_store.get(conversation.tenant_id, conversation.id)
    if pending_state is not None:
        logger.info(
            "读取到 AI 待补槽状态：tenant_id=%s conversation_id=%s intent=%s required_entities=%s",
            conversation.tenant_id,
            conversation.id,
            pending_state.intent,
            pending_state.required_entities,
        )

    result = await IntentRecognitionPipeline().recognize_and_route(
        customer_message.content or "",
        pending_state=pending_state,
    )
    logger.info(
        "AI 路由完成：tenant_id=%s conversation_id=%s message_id=%s route=%s intent=%s skill=%s confidence=%.4f multi=%s clarify=%s hits=%s",
        conversation.tenant_id,
        conversation.id,
        customer_message.id,
        result.route,
        result.primary_intent,
        result.skill,
        result.confidence,
        result.is_multi_intent,
        result.need_clarification,
        len(result.hits),
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

    router = MessageRouter()
    handler = router.resolve(result)

    if handler.reply_sender_type is None:
        logger.info(
            "AI 路由无需回复：conversation_id=%s message_id=%s route=%s elapsed_ms=%.0f",
            conversation.id,
            customer_message.id,
            result.route,
            (time.perf_counter() - started) * 1000,
        )
        return

    if handler.clear_pending_state:
        await pending_store.delete(conversation.tenant_id, conversation.id)

    if handler.transfer_to_human:
        logger.warning(
            "AI 路由到人工：tenant_id=%s conversation_id=%s message_id=%s intent=%s reason=%s",
            conversation.tenant_id,
            conversation.id,
            customer_message.id,
            result.primary_intent,
            result.reason,
        )
        await _mark_pending_human(db, conversation, result.reason or result.primary_intent or "需要人工处理")

    # 首次 AI 对话时，发送系统提示告知客户
    if handler.send_ai_greeting and "ai_greeting_sent" not in (conversation.tags or []):
        await _create_and_broadcast_system_message(
            db,
            conversation,
            "您好，我是 AI 智能助手，正在为您服务。如需人工客服，请随时告知。",
            metadata={"type": "ai_greeting"},
        )
        conversation.tags = (conversation.tags or []) + ["ai_greeting_sent"]

    agent_ctx = (
        AgentContext(
            db=db,
            tenant_id=conversation.tenant_id,
            conversation_id=conversation.id,
            contact_id=conversation.contact_id,
        )
        if handler.requires_agent_context
        else None
    )

    if handler.show_typing:
        await _publish_typing(conversation, True)

    dispatch_started = time.perf_counter()
    try:
        content = (
            await router.render(
                result,
                handler=handler,
                agent_context=agent_ctx,
                on_chunk=lambda chunk: manager.publish(
                    conversation.id,
                    {"type": "ai.message.chunk", "content": chunk},
                ),
            )
        ).strip()
    finally:
        if handler.show_typing:
            await _publish_typing(conversation, False)

    logger.info(
        "AI 回复生成完成：conversation_id=%s route=%s sender_type=%s content_len=%s elapsed_ms=%.0f",
        conversation.id,
        result.route,
        handler.reply_sender_type,
        len(content),
        (time.perf_counter() - dispatch_started) * 1000,
    )

    if not content:
        logger.warning(
            "AI 生成内容为空：conversation_id=%s message_id=%s route=%s intent=%s",
            conversation.id,
            customer_message.id,
            result.route,
            result.primary_intent,
        )
        return

    await _create_deliver_and_broadcast_reply_message(
        db,
        conversation,
        content,
        sender_type=handler.reply_sender_type or "AI",
        metadata={
            "ai_route": result.route,
            "skill": result.skill,
            "intent": result.primary_intent,
            "confidence": result.confidence,
            "is_multi_intent": result.is_multi_intent,
        },
    )
    logger.info(
        "AI 处理完成：tenant_id=%s conversation_id=%s message_id=%s route=%s elapsed_ms=%.0f",
        conversation.tenant_id,
        conversation.id,
        customer_message.id,
        result.route,
        (time.perf_counter() - started) * 1000,
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
        logger.info(
            "会话已标记为等待人工：tenant_id=%s conversation_id=%s reason=%s",
            conversation.tenant_id,
            conversation.id,
            reason,
        )
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
    logger.info(
        "系统消息已创建：conversation_id=%s message_id=%s metadata=%s",
        conversation.id,
        message.id,
        metadata,
    )
    await manager.publish(conversation.id, {"type": "message.created", "message": message_payload(message)})


async def _create_deliver_and_broadcast_reply_message(
    db: AsyncSession,
    conversation: Conversation,
    content: str,
    *,
    sender_type: str,
    metadata: dict,
) -> None:
    conversation, message = await conversation_service.create_message(
        db,
        conversation.id,
        conversation.tenant_id,
        MessageCreate(sender_type=sender_type, content_type="text", content=content, metadata=metadata),
    )
    message = await outbound_message_service.deliver_message(db, conversation, message)
    logger.info(
        "AI 回复消息已创建：conversation_id=%s message_id=%s sender_type=%s content_len=%s metadata=%s",
        conversation.id,
        message.id,
        sender_type,
        len(content),
        metadata,
    )
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
