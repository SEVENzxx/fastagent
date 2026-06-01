"""AI 入站消息处理编排。"""

from __future__ import annotations

import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.websocket_manager import manager
from app.models.conversation import Conversation, Message
from app.schemas.conversation import ConversationUpdate, MessageCreate
from app.services import conversation_service, outbound_message_service
from app.services.ai.agent.types import AgentContext
from app.services.ai.intent.pending_state_store import PendingStateStore
from app.services.ai.intent.pipeline import IntentRecognitionPipeline
from app.services.ai.message_router import MessageRouter
from app.services.usage_service import bind_usage_context

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
    """ 对客户入站消息执行 AI 识别、路由和回复 """

    # ── 1: 已关闭或坐席正在处理的会话，不进入 AI ──
    if conversation.status in {"closed", "human_processing"}:
        return

    # ── 2: pending_human 排队状态 — 坐席已接管→跳过；无坐席→AI 兜底 ──
    if conversation.status == "pending_human":
        # 检查是否有坐席已接管（employee_id 非空）
        if conversation.employee_id is not None:
            return
        # ── 3: 客户主动要求切回 AI ──
        customer_text = (customer_message.content or "").strip()
        if customer_text == "智能客服":
            logger.info("客户要求切回 AI：conversation_id=%s, 恢复 ai_processing", conversation.id, )
            await conversation_service.update_conversation(
                db,
                conversation.id,
                conversation.tenant_id,
                ConversationUpdate(status="ai_processing", handling_type="ai_only"),
            )
            # 刷新 conversation 对象后继续走正常 AI 管线
            conversation = await conversation_service.get_conversation(
                db, conversation.id, conversation.tenant_id
            )
            # 继续往下走 AI 流程（不 return）
        else:
            # 2b: 无坐席在线，AI 代为回复排队兜底
            queue_msg = (
                "当前人工客服繁忙，您正在排队等待中，请耐心等候。"
                "如需继续由智能客服为您服务，请回复「智能客服」。"
            )
            await _create_deliver_and_broadcast_reply_message(
                db,
                conversation,
                queue_msg,
                sender_type="SYSTEM",
                metadata={"type": "queue_notice", "status": "pending_human"},
            )
            return
    # ── 3 续：已切回 ai_processing，继续下面的 AI 管线 ──
    # ── 4: 已由人工接待的会话 → 跳过 AI ──
    if conversation.handling_type == "human":
        logger.info("跳过 AI 处理：conversation_id=%s 已由人工接待", conversation.id, )
        return

    # ── 5: 过滤非客户文本消息（图片/系统通知/坐席回复等不处理）──
    if customer_message.sender_type != "CUSTOMER" or customer_message.content_type != "text":
        return

    started = time.perf_counter()
    # ── 6: 绑定用量计量上下文 ──
    # ContextVar 绑定 (tenant_id, conversation_id, message_id)，
    # 后续意图精判、Agent 回复等所有 LLM 调用自动记账到该租户。
    bind_usage_context(
        tenant_id=conversation.tenant_id,
        conversation_id=conversation.id,
        message_id=customer_message.id,
    )

    # ── 7: 读取 PendingState（多轮槽位补全）──
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

    # ── 8: 意图识别流水线 → 输出 RoutedIntent (route + skill + confidence) ──
    result = await IntentRecognitionPipeline().recognize_and_route(
        customer_message.content or "",
        pending_state=pending_state,
    )

    # ── 9: WebSocket 广播 ai.routed 事件（前端可实时展示路由结果）──
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

    # ── 10: 路由分发 → MessageRouter → Handler (SILENT / GENERAL_REPLY / AGENT / HUMAN) ──
    router = MessageRouter()
    handler = router.resolve(result)

    # ── 11: Silent / 无需回复（reply_sender_type=None）→ 直接返回 ──
    if handler.reply_sender_type is None:
        return

    # ── 12: 清理 PendingState ──
    # 转人工 / 明确回复 → AI 不需要再追问槽位，清除 Redis 里的待补状态
    if handler.clear_pending_state:
        await pending_store.delete(conversation.tenant_id, conversation.id)

    # ── 13: 转人工 → 自动分配在线坐席 + 通知 ──
    if handler.transfer_to_human:
        await _mark_pending_human(db, conversation, result.reason or result.primary_intent or "需要人工处理")

    # ── 14: 首次 AI 对话 → 发送 AI 问候语（从租户配置读取）──
    if handler.send_ai_greeting and "ai_greeting_sent" not in (conversation.tags or []):
        from app.services.ai.tenant_ai_config import get_ai_greeting
        greeting = await get_ai_greeting(db, conversation.tenant_id)
        await _create_and_broadcast_system_message(
            db,
            conversation,
            greeting,
            metadata={"type": "ai_greeting"},
        )
        conversation.tags = (conversation.tags or []) + ["ai_greeting_sent"]

    # ── 15: 构建 AgentContext ──
    # 仅 AGENT 路由需要：传 db session + tenant_id + conversation_id + contact_id，
    # 供 LangGraph Agent 的 Skill 函数调用（如 create_order / search_products）
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

    # ── 16: 流式渲染 AI 回复（先发 typing 指示，再 SSE 推送 chunk）──
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
        logger.info("AI 回复生成结果为空，跳过后续处理：conversation_id=%s route=%s", conversation.id, result.route)
        return

    # ── 17: 组装回复 metadata（路由信息 + 订单卡片）──
    metadata: dict = {
        "ai_route": result.route,
        "skill": result.skill,
        "intent": result.primary_intent,
        "confidence": result.confidence,
        "is_multi_intent": result.is_multi_intent,
    }

    # 附带 order card 数据（来自 Skill 工具调用结果，如 create_order）
    order_cards = _extract_order_cards(handler)
    if order_cards:
        metadata["order_cards"] = order_cards

    # ── 18: 落库 + WebSocket 广播 + 企微（或其他渠道）出站投递 ──
    await _create_deliver_and_broadcast_reply_message(
        db,
        conversation,
        content,
        sender_type=handler.reply_sender_type or "AI",
        metadata=metadata,
    )


async def _mark_pending_human(db: AsyncSession, conversation: Conversation, reason: str) -> None:
    """将会话标记为待人工处理，尝试自动分配在线坐席。

    A - 查同租户在线/离开的坐席（排除离线/busy/已删除）
    B - 找到 → 自动分配 employee_id；没找到 → 留空
    C - 更新会话 status="pending_human" + handling_type="human"
    D - 创建系统通知（已分配坐席则定向通知，否则广播"暂无在线坐席"）
    E - WebSocket 广播 conversation.updated 事件
    """
    from app.models.employee import Employee

    # A-B: 查找同租户在线坐席
    online_agent = await db.scalar(
        select(Employee).where(
            Employee.tenant_id == conversation.tenant_id,
            Employee.deleted_at.is_(None),
            Employee.online_status.in_(["online", "away"]),
        ).order_by(Employee.last_login_at.desc()).limit(1)
    )

    assigned_employee_id = None
    if online_agent is not None:
        assigned_employee_id = online_agent.id

    updated = await conversation_service.update_conversation(
        db,
        conversation.id,
        conversation.tenant_id,
        ConversationUpdate(
            status="pending_human",
            handling_type="human",
            is_transferred=True,
            transfer_reason=reason,
            employee_id=assigned_employee_id,
        ),
    )
    if updated is not None:
        # 创建系统通知提醒坐席有会话需要人工接管
        from app.services.operations_service import create_notification
        notice_content = (
            f"会话 {conversation.id} 因\"{reason}\"转入人工处理，已自动分配给坐席 #{assigned_employee_id}。"
            if assigned_employee_id
            else f"会话 {conversation.id} 因\"{reason}\"转入人工处理，当前无在线坐席，请在坐席上线后及时接管。"
        )
        await create_notification(
            db,
            type="human_transfer",
            tenant_id=conversation.tenant_id,
            level="warning",
            title="会话已转入人工队列",
            content=notice_content,
            resource_type="conversation",
            resource_id=conversation.id,
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


def _extract_order_cards(handler) -> list[dict] | None:
    """从 handler 的 tool_results 中提取订单卡片数据。"""
    tool_results: list[dict] = getattr(handler, "last_tool_results", []) or []
    cards: list[dict] = []
    order_skills = {"create_order", "confirm_order", "manage_order"}
    for r in tool_results:
        if r.get("skill_name") in order_skills and r.get("ok"):
            result_data = r.get("result")
            if isinstance(result_data, dict):
                cards.append({
                    "skill_name": r["skill_name"],
                    "order_id": result_data.get("order_id"),
                    "status": result_data.get("status"),
                    "status_label": result_data.get("status_label"),
                    "total_amount": result_data.get("total_amount"),
                    "payable_amount": result_data.get("payable_amount"),
                    "items": result_data.get("items"),
                    "message": result_data.get("message"),
                })
    return cards or None
