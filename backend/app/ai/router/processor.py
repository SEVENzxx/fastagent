"""AI 入站消息处理编排。

采用 Pipeline 步骤模式，每个步骤是可测试的独立单元。
编排器只负责：① 按序执行步骤 ② 短路跳过 ③ 统一释放资源。
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.websocket_manager import manager
from app.models.conversation import Conversation, Message
from app.schemas.conversation import ConversationUpdate, MessageCreate
from app.services import conversation_service, outbound_message_service
from app.ai.agent.argument_pending import build_pending_state_from_tool_result
from app.ai.agent.types import AgentContext
from app.ai.commerce_flow import handle_commerce_flow, CommerceFlowResult
from app.ai.memory.conversation_state import ConversationStateStore
from app.ai.memory.message_buffer import ConversationMessageBuffer
from app.ai.memory.pending_state import PendingStateStore
from app.ai.classifier.pipeline import IntentRecognitionPipeline
from app.ai.router.message_router import MessageRouter
from app.services.usage_service import bind_usage_context

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
#   Pipeline 数据上下文
# ──────────────────────────────────────────────

@dataclass
class ProcessingContext:
    """AI 消息处理的管道上下文，在步骤间传递。"""

    db: AsyncSession
    conversation: Conversation
    customer_message: Message
    customer_text: str = ""
    message_buffer: ConversationMessageBuffer | None = None
    pending_state: Any = None
    agent_ctx: AgentContext | None = None
    batch: Any = None

    # 步骤执行结果（后续步骤可读取）
    commerce_result: CommerceFlowResult | None = None
    routed_intent: Any = None
    render_result: RenderResult | None = None
    should_stop: bool = False  # 设为 True 则终止后续步骤
    release_lock: bool = True  # 结束时是否释放锁


# ──────────────────────────────────────────────
#   Pipeline 步骤基类
# ──────────────────────────────────────────────

class PipelineStep(ABC):
    """一步处理。子类实现 execute()，返回 True 继续，False 短路。"""

    @abstractmethod
    async def execute(self, ctx: ProcessingContext) -> bool:
        ...


# ──────────────────────────────────────────────
#   各步骤实现
# ──────────────────────────────────────────────

class FilterClosedOrHumanProcessing(PipelineStep):
    """步骤 1: 已关闭 / human_processing → 跳过"""

    async def execute(self, ctx: ProcessingContext) -> bool:
        if ctx.conversation.status in {Conversation.STATUS_CLOSED, Conversation.STATUS_HUMAN_PROCESSING}:
            ctx.should_stop = True
        return True


class FilterPendingHuman(PipelineStep):
    """步骤 2-4: pending_human 排队状态处理"""

    async def execute(self, ctx: ProcessingContext) -> bool:
        if ctx.conversation.status != Conversation.STATUS_PENDING_HUMAN:
            return True

        if ctx.conversation.employee_id is not None:
            ctx.should_stop = True  # 坐席已接管
            return True

        text = (ctx.customer_message.content or "").strip()
        if text == "智能客服":
            logger.info("客户要求切回 AI：conversation_id=%s", ctx.conversation.id)
            await conversation_service.update_conversation(
                ctx.db, ctx.conversation.id, ctx.conversation.tenant_id,
                ConversationUpdate(
                    status=Conversation.STATUS_AI_PROCESSING,
                    handling_type=Conversation.HANDLING_AI_ONLY,
                ),
            )
            ctx.conversation = await conversation_service.get_conversation(
                ctx.db, ctx.conversation.id, ctx.conversation.tenant_id,
            )
            return True  # 继续走 AI 管线

        queue_msg = (
            "当前人工客服繁忙，您正在排队等待中，请耐心等候。"
            "如需继续由智能客服为您服务，请回复「智能客服」。"
        )
        await _create_deliver_and_broadcast_reply_message(
            ctx.db, ctx.conversation, queue_msg,
            sender_type="SYSTEM",
            metadata={"type": "queue_notice", "status": "pending_human"},
        )
        ctx.should_stop = True
        return True


class FilterHandlingHuman(PipelineStep):
    """步骤 5: 已由人工接待 → 跳过"""

    async def execute(self, ctx: ProcessingContext) -> bool:
        if ctx.conversation.handling_type == Conversation.HANDLING_HUMAN:
            ctx.should_stop = True
        return True


class FilterNonCustomerText(PipelineStep):
    """步骤 6: 非客户文本消息 → 跳过"""

    async def execute(self, ctx: ProcessingContext) -> bool:
        msg = ctx.customer_message
        if msg.sender_type != Conversation.SENDER_CUSTOMER or msg.content_type != "text":
            ctx.should_stop = True
        return True


class BufferAndDeduplicate(PipelineStep):
    """步骤 7: 同会话快速消息缓冲 + 串行锁"""

    async def execute(self, ctx: ProcessingContext) -> bool:
        text = (ctx.customer_message.content or "").strip()
        buf = ConversationMessageBuffer()
        ctx.message_buffer = buf
        try:
            batch = await buf.wait_for_batch(
                tenant_id=ctx.conversation.tenant_id,
                conversation_id=ctx.conversation.id,
                message_id=ctx.customer_message.id,
                text=text,
            )
        except Exception as exc:
            logger.warning(
                "AI 消息缓冲失败，降级为单条处理：conversation_id=%s message_id=%s error=%s",
                ctx.conversation.id, ctx.customer_message.id, exc,
            )
            batch = None
            ctx.message_buffer = None  # 标记降级，短路时不拦截

        # batch 为空分两种情况：
        #   a) 缓冲器正常→消息正在缓冲中，等待后续合并 → 短路
        #   b) 缓冲器异常降级→视为单条消息直接处理
        if batch is None:
            if ctx.message_buffer is not None:
                ctx.should_stop = True
            return True

        ctx.batch = batch
        ctx.customer_text = batch.text.strip()
        if not ctx.customer_text:
            ctx.should_stop = True
            return True

        logger.info(
            "AI 消息缓冲批次就绪：conversation_id=%s count=%s message_ids=%s text_len=%s",
            ctx.conversation.id, batch.message_count, batch.message_ids, len(ctx.customer_text),
        )
        return True


class ExecuteCommerceFlow(PipelineStep):
    """步骤 8-10: 商品/订单多轮状态机优先处理"""

    async def execute(self, ctx: ProcessingContext) -> bool:
        bind_usage_context(
            tenant_id=ctx.conversation.tenant_id,
            conversation_id=ctx.conversation.id,
            message_id=ctx.customer_message.id,
        )

        pending_store = PendingStateStore()
        ctx.pending_state = await pending_store.get(ctx.conversation.tenant_id, ctx.conversation.id)
        if ctx.pending_state is not None:
            logger.info(
                "待补槽状态：tenant_id=%s conversation_id=%s intent=%s required_entities=%s",
                ctx.conversation.tenant_id, ctx.conversation.id,
                ctx.pending_state.intent, ctx.pending_state.required_entities,
            )

        ctx.agent_ctx = AgentContext(
            db=ctx.db,
            tenant_id=ctx.conversation.tenant_id,
            conversation_id=ctx.conversation.id,
            contact_id=ctx.conversation.contact_id,
            pending_state=ctx.pending_state,
        )

        commerce_store = ConversationStateStore()
        commerce_state = await commerce_store.get(ctx.conversation.tenant_id, ctx.conversation.id)
        result = await handle_commerce_flow(ctx.agent_ctx, ctx.customer_text, commerce_state)

        if result is None:
            return True  # 未命中状态机，继续走通用意图识别

        # 状态机命中，直接输出回复
        ctx.commerce_result = result
        await commerce_store.set(ctx.conversation.tenant_id, ctx.conversation.id, result.state)
        metadata = {
            "ai_route": "COMMERCE_FLOW",
            "skill": result.state.last_agent_action,
            "intent": result.state.last_intent,
            "confidence": 1.0,
            "is_multi_intent": False,
            "conversation_state": result.state.to_dict(),
            "merged_customer_text": ctx.customer_text,
        }
        order_cards = _extract_order_cards(result.tool_results)
        if order_cards:
            metadata["order_cards"] = order_cards
        logger.info(
            "商品订单状态机已处理：conversation_id=%s stage=%s intent=%s action=%s content_len=%s",
            ctx.conversation.id, result.state.stage.value,
            result.state.last_intent, result.state.last_agent_action, len(result.text),
        )
        await _create_deliver_and_broadcast_reply_message(
            ctx.db, ctx.conversation, result.text.strip(),
            sender_type="AI", metadata=metadata,
        )
        ctx.should_stop = True
        return True


class RecognizeIntent(PipelineStep):
    """步骤 11: 意图识别 + 路由分发"""

    async def execute(self, ctx: ProcessingContext) -> bool:
        result = await IntentRecognitionPipeline().recognize_and_route(
            ctx.customer_text,
            tenant_id=ctx.conversation.tenant_id,
            pending_state=ctx.pending_state,
        )
        ctx.routed_intent = result
        return True


class HandleSilent(PipelineStep):
    """步骤 12-13: Silent 路由 → 直接返回"""

    async def execute(self, ctx: ProcessingContext) -> bool:
        router = MessageRouter()
        handler = router.resolve(ctx.routed_intent)

        if handler.reply_sender_type is None:
            ctx.should_stop = True
            return True

        # 清理 PendingState
        if handler.clear_pending_state:
            pending_store = PendingStateStore()
            await pending_store.delete(ctx.conversation.tenant_id, ctx.conversation.id)

        # 转人工
        if handler.transfer_to_human:
            await _mark_pending_human(
                ctx.db, ctx.conversation,
                ctx.routed_intent.reason or ctx.routed_intent.primary_intent or "需要人工处理",
            )

        # 首次 AI 问候
        if handler.send_ai_greeting and "ai_greeting_sent" not in (ctx.conversation.tags or []):
            from app.ai.tenant_config import get_ai_greeting
            greeting = await get_ai_greeting(ctx.db, ctx.conversation.tenant_id)
            await _create_and_broadcast_system_message(
                ctx.db, ctx.conversation, greeting,
                metadata={"type": "ai_greeting"},
            )
            ctx.conversation.tags = (ctx.conversation.tags or []) + ["ai_greeting_sent"]

        self._handler = handler
        self._router = router
        return True


class RenderReply(PipelineStep):
    """步骤 14-17: 流式渲染 AI 回复"""

    def __init__(self) -> None:
        self._handler: Any = None
        self._router: Any = None

    async def execute(self, ctx: ProcessingContext) -> bool:
        handler = self._handler
        router = self._router

        if handler.show_typing:
            await _publish_typing(ctx.conversation, True)

        dispatch_started = time.perf_counter()
        try:
            render_result = await router.render(
                ctx.routed_intent,
                handler=handler,
                agent_context=ctx.agent_ctx,
                on_chunk=lambda chunk: manager.publish(
                    ctx.conversation.id,
                    {"type": "ai.message.chunk", "content": chunk},
                ),
            )
            content = render_result.text.strip()
        finally:
            if handler.show_typing:
                await _publish_typing(ctx.conversation, False)

        logger.info(
            "AI 回复生成完成：conversation_id=%s route=%s sender_type=%s content_len=%s elapsed_ms=%.0f",
            ctx.conversation.id, ctx.routed_intent.route, handler.reply_sender_type,
            len(content), (time.perf_counter() - dispatch_started) * 1000,
        )

        if not content:
            ctx.should_stop = True
            return True

        ctx.render_result = render_result

        # 组装回复 metadata
        metadata: dict = {
            "ai_route": ctx.routed_intent.route,
            "skill": ctx.routed_intent.skill,
            "intent": ctx.routed_intent.primary_intent,
            "confidence": ctx.routed_intent.confidence,
            "is_multi_intent": ctx.routed_intent.is_multi_intent,
            "merged_customer_text": ctx.customer_text,
        }
        order_cards = _extract_order_cards(render_result.tool_results)
        if order_cards:
            metadata["order_cards"] = order_cards

        # PendingState 持久化
        pending_store = PendingStateStore()
        pending_to_save = _build_pending_state_from_tool_results(
            render_result.tool_results,
            intent=ctx.routed_intent.primary_intent,
        )
        if pending_to_save is not None:
            await pending_store.set(ctx.conversation.tenant_id, ctx.conversation.id, pending_to_save)
        elif ctx.pending_state is not None and _has_successful_agent_tool_result(render_result.tool_results):
            await pending_store.delete(ctx.conversation.tenant_id, ctx.conversation.id)

        # 落库 + WebSocket + 出站
        await _create_deliver_and_broadcast_reply_message(
            ctx.db, ctx.conversation, content,
            sender_type=handler.reply_sender_type or "AI",
            metadata=metadata,
        )
        ctx.should_stop = True
        return True


# ──────────────────────────────────────────────
#   编排器
# ──────────────────────────────────────────────

async def process_customer_message_with_ai(
    db: AsyncSession,
    conversation: Conversation,
    customer_message: Message,
) -> None:
    """AI 消息处理编排入口。按序执行步骤管线，遇到 should_stop 提前终止。"""

    ctx = ProcessingContext(
        db=db,
        conversation=conversation,
        customer_message=customer_message,
    )
    steps: list[PipelineStep] = [
        FilterClosedOrHumanProcessing(),
        FilterPendingHuman(),
        FilterHandlingHuman(),
        FilterNonCustomerText(),
        BufferAndDeduplicate(),
        ExecuteCommerceFlow(),
        RecognizeIntent(),
        HandleSilent(),
        RenderReply(),
    ]

    try:
        for step in steps:
            await step.execute(ctx)
            if ctx.should_stop:
                break
    finally:
        if ctx.message_buffer is not None and ctx.release_lock:
            await ctx.message_buffer.release_lock(ctx.conversation.tenant_id, ctx.conversation.id)


# ──────────────────────────────────────────────
#   辅助函数（消息序列化、落库、广播、转人工等）
# ──────────────────────────────────────────────

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
    order_skills = {
        "create_order",
        "create_order_draft",
        "update_order_draft",
        "update_draft_order_quantity",
        "confirm_order",
        "manage_order",
    }
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
