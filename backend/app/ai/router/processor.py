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
from app.ai.agent.argument_pending import build_pending_state_from_tool_result
from app.ai.agent.types import AgentContext
from app.ai.commerce_flow import handle_commerce_flow
from app.ai.memory.conversation_state import ConversationStateStore
from app.ai.memory.pending_state import PendingStateStore
from app.ai.classifier.pipeline import IntentRecognitionPipeline
from app.ai.router.message_router import MessageRouter, RenderResult
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
    """对客户入站消息执行 AI 识别、路由和回复。

    ═══════════════ 前置过滤 ═══════════════
      1. closed / human_processing           → 跳过
      2. pending_human + 坐席已接管          → 跳过
      3. pending_human + 客户说「智能客服」  → 切回 ai_processing，继续走 AI
      4. pending_human + 无坐席 + 其他消息   → 排队兜底提示
      5. handling_type=human                 → 跳过（已由人工接待）
      6. 非客户文本消息                      → 跳过

    ═══════════════ 主管线 ═══════════════
      7.  bind_usage_context    绑定计量上下文（ContextVar）
      8.  读取 PendingState      多轮槽位补全
      9.  意图识别流水线         → RoutedIntent (route + skill + confidence)
      10. WebSocket 广播          ai.routed 事件
      11. 路由分发               MessageRouter → Handler
      12. Silent / 无需回复      → 直接返回
      13. 清理 PendingState      转人工 / 明确回复时清除
      14. 转人工                 自动分配在线坐席 + 通知
      15. 首次 AI 问候          租户配置读取
      16. 构建 AgentContext      仅 AGENT 路由
      17. 流式渲染 AI 回复      SSE chunk 推送
      18. 组装 metadata          路由信息 + 订单卡片
      19. 落库 + 广播 + 投递     Message 表 → WS → 渠道出站
    """

    # ═══════════════════════ 前置过滤 ═══════════════════════

    # ── 1: closed / human_processing → 跳过 ──
    if conversation.status in {Conversation.STATUS_CLOSED, Conversation.STATUS_HUMAN_PROCESSING}:
        return

    # ── 2-4: pending_human 排队状态 ──
    if conversation.status == Conversation.STATUS_PENDING_HUMAN:
        # ── 2: 坐席已接管 → 跳过 ──
        if conversation.employee_id is not None:
            return

        customer_text = (customer_message.content or "").strip()

        # ── 3: 客户说「智能客服」→ 切回 AI ──
        if customer_text == "智能客服":
            logger.info("客户要求切回 AI：conversation_id=%s", conversation.id)
            await conversation_service.update_conversation(
                db,
                conversation.id,
                conversation.tenant_id,
                ConversationUpdate(
                    status=Conversation.STATUS_AI_PROCESSING,
                    handling_type=Conversation.HANDLING_AI_ONLY,
                ),
            )
            conversation = await conversation_service.get_conversation(
                db, conversation.id, conversation.tenant_id
            )
            # 不 return，继续走下面的 AI 管线

        else:
            # ── 4: 无坐席在线 → 排队兜底提示 ──
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

    # ── 5: 已由人工接待 → 跳过 ──
    if conversation.handling_type == Conversation.HANDLING_HUMAN:
        return

    # ── 6: 过滤非客户文本消息 ──
    if customer_message.sender_type != Conversation.SENDER_CUSTOMER or customer_message.content_type != "text":
        return

    # ═══════════════════════ 主管线 ═══════════════════════

    # ── 7: 绑定计量上下文 ──
    bind_usage_context(
        tenant_id=conversation.tenant_id,
        conversation_id=conversation.id,
        message_id=customer_message.id,
    )

    # ── 8: 读取 PendingState（多轮槽位补全）──
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

    # ── 9: 商品咨询/订单草稿多轮状态机优先处理 ──
    # 必须在通用意图识别之前执行，否则“确认”等短句可能先被 SILENT 规则吞掉。
    agent_ctx = AgentContext(
        db=db,
        tenant_id=conversation.tenant_id,
        conversation_id=conversation.id,
        contact_id=conversation.contact_id,
        pending_state=pending_state,
    )
    commerce_store = ConversationStateStore()
    commerce_state = await commerce_store.get(conversation.tenant_id, conversation.id)
    commerce_result = await handle_commerce_flow(
        agent_ctx,
        customer_message.content or "",
        commerce_state,
    )
    if commerce_result is not None:
        await commerce_store.set(conversation.tenant_id, conversation.id, commerce_result.state)
        metadata = {
            "ai_route": "COMMERCE_FLOW",
            "skill": commerce_result.state.last_agent_action,
            "intent": commerce_result.state.last_intent,
            "confidence": 1.0,
            "is_multi_intent": False,
            "conversation_state": commerce_result.state.to_dict(),
        }
        order_cards = _extract_order_cards(commerce_result.tool_results)
        if order_cards:
            metadata["order_cards"] = order_cards
        logger.info(
            "商品订单状态机已处理：conversation_id=%s stage=%s intent=%s action=%s content_len=%s",
            conversation.id,
            commerce_result.state.stage.value,
            commerce_result.state.last_intent,
            commerce_result.state.last_agent_action,
            len(commerce_result.text),
        )
        await _create_deliver_and_broadcast_reply_message(
            db,
            conversation,
            commerce_result.text.strip(),
            sender_type="AI",
            metadata=metadata,
        )
        return

    # ── 10: 意图识别流水线 ──
    result = await IntentRecognitionPipeline().recognize_and_route(
        customer_message.content or "",
        tenant_id=conversation.tenant_id,
        pending_state=pending_state,
    )

    # ── 11: 路由分发 → Handler ──
    router = MessageRouter()
    handler = router.resolve(result)

    # ── 12: Silent → 直接返回 ──
    if handler.reply_sender_type is None:
        return

    # ── 13: 清理 PendingState ──
    if handler.clear_pending_state:
        await pending_store.delete(conversation.tenant_id, conversation.id)

    # ── 14: 转人工 ──
    if handler.transfer_to_human:
        await _mark_pending_human(db, conversation, result.reason or result.primary_intent or "需要人工处理")

    # ── 15: 首次 AI 问候 ──
    if handler.send_ai_greeting and "ai_greeting_sent" not in (conversation.tags or []):
        from app.ai.tenant_config import get_ai_greeting
        greeting = await get_ai_greeting(db, conversation.tenant_id)
        await _create_and_broadcast_system_message(
            db,
            conversation,
            greeting,
            metadata={"type": "ai_greeting"},
        )
        conversation.tags = (conversation.tags or []) + ["ai_greeting_sent"]

    # ── 16: 流式渲染 AI 回复 ──
    if handler.show_typing:
        await _publish_typing(conversation, True)

    dispatch_started = time.perf_counter()
    try:
        render_result = (
            await router.render(
                result,
                handler=handler,
                agent_context=agent_ctx,
                on_chunk=lambda chunk: manager.publish(
                    conversation.id,
                    {"type": "ai.message.chunk", "content": chunk},
                ),
            )
        )
        content = render_result.text.strip()
    finally:
        if handler.show_typing:
            await _publish_typing(conversation, False)

    logger.info(
        "AI 回复生成完成：conversation_id=%s route=%s sender_type=%s content_len=%s elapsed_ms=%.0f",
        conversation.id, result.route, handler.reply_sender_type,
        len(content), (time.perf_counter() - dispatch_started) * 1000,
    )

    if not content:
        return

    # ── 18: 组装回复 metadata ──
    metadata: dict = {
        "ai_route": result.route,
        "skill": result.skill,
        "intent": result.primary_intent,
        "confidence": result.confidence,
        "is_multi_intent": result.is_multi_intent,
    }
    order_cards = _extract_order_cards(render_result.tool_results)
    if order_cards:
        metadata["order_cards"] = order_cards

    pending_to_save = _build_pending_state_from_tool_results(
        render_result.tool_results,
        intent=result.primary_intent,
    )
    if pending_to_save is not None:
        await pending_store.set(conversation.tenant_id, conversation.id, pending_to_save)
    elif pending_state is not None and _has_successful_agent_tool_result(render_result.tool_results):
        await pending_store.delete(conversation.tenant_id, conversation.id)

    # ── 19: 落库 + WebSocket 广播 + 渠道出站投递 ──
    await _create_deliver_and_broadcast_reply_message(
        db,
        conversation,
        content,
        sender_type=handler.reply_sender_type or "AI",
        metadata=metadata,
    )


async def _mark_pending_human(db: AsyncSession, conversation: Conversation, reason: str) -> None:
    """将会话标记为待人工处理，尝试自动分配在线坐席。

    A - 查同租户在线/离开的坐席
    B - 找到 → 自动分配 employee_id；没找到 → 留空
    C - 更新会话 STATUS_PENDING_HUMAN + HANDLING_HUMAN
    D - 创建系统通知
    E - WebSocket 广播 conversation.updated
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
            status=Conversation.STATUS_PENDING_HUMAN,
            handling_type=Conversation.HANDLING_HUMAN,
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
    """落库 SYSTEM 消息 → 出站投递 → WebSocket 广播。"""
    # ── 1: 落库 ──
    _, message = await conversation_service.create_message(
        db,
        conversation.id,
        conversation.tenant_id,
        MessageCreate(sender_type="SYSTEM", content_type="text", content=content, metadata=metadata),
    )
    # ── 2: 渠道投递 + 广播 ──
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
    """落库消息 → 渠道出站投递 → WebSocket 广播。"""

    # ── 1: 消息落库 ──
    conversation, message = await conversation_service.create_message(
        db,
        conversation.id,
        conversation.tenant_id,
        MessageCreate(sender_type=sender_type, content_type="text", content=content, metadata=metadata),
    )

    # ── 2: 渠道出站投递（企微等）──
    message = await outbound_message_service.deliver_message(db, conversation, message)

    # ── 3: WebSocket 广播到前端坐席工作台 ──
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


def _extract_order_cards(tool_results: list[dict]) -> list[dict] | None:
    """从 tool_results 中提取订单卡片数据。"""
    cards: list[dict] = []
    order_skills = {"create_order", "create_order_draft", "update_order_draft", "confirm_order", "manage_order"}
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


def _build_pending_state_from_tool_results(tool_results: list[dict], *, intent: str | None):
    for result in tool_results:
        skill_name = result.get("skill_name")
        if not isinstance(skill_name, str):
            continue
        pending = build_pending_state_from_tool_result(
            result,
            intent=intent,
            skill_name=skill_name,
        )
        if pending is not None:
            return pending
    return None


def _has_successful_agent_tool_result(tool_results: list[dict]) -> bool:
    return any(bool(result.get("ok")) for result in tool_results)
