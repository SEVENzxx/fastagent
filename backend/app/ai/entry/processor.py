"""AI 入站消息处理编排。

采用 Pipeline 步骤模式，每个步骤是可测试的独立单元。
编排器只负责：按序执行步骤 → 短路跳过 → 统一释放资源。

主链路：Filters → RunAssistantOrchestrator（AssistantService 主编排入口）
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# 模块级 AssistantService 单例（延迟初始化）
_assistant_service: Any = None


def _get_assistant_service() -> Any:
    global _assistant_service
    if _assistant_service is None:
        from app.ai.assistant.service import AssistantService

        _assistant_service = AssistantService()
    return _assistant_service

from app.ai.entry.buffer import ConversationMessageBuffer
from app.ai.observability import observe_trace
from app.core.websocket_manager import manager
from app.models.conversation import Conversation, Message
from app.schemas.conversation import ConversationUpdate, MessageCreate
from app.services import conversation_service, outbound_message_service
from app.common.constants.ai import AI_ROUTE_ASSISTANT_SERVICE, SWITCH_TO_AI_KEYWORD
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
    batch: Any = None
    should_stop: bool = False
    release_lock: bool = True


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
    """步骤 1: 已关闭 / human_processing 的会话 → 跳过"""

    async def execute(self, ctx: ProcessingContext) -> bool:
        if ctx.conversation.status in {Conversation.STATUS_CLOSED, Conversation.STATUS_HUMAN_PROCESSING}:
            ctx.should_stop = True
        return True


class FilterPendingHuman(PipelineStep):
    """步骤 2: pending_human 排队 / 切回 AI / 兜底提示"""

    async def execute(self, ctx: ProcessingContext) -> bool:
        if ctx.conversation.status != Conversation.STATUS_PENDING_HUMAN:
            return True

        if ctx.conversation.employee_id is not None:
            ctx.should_stop = True
            return True

        text = (ctx.customer_message.content or "").strip()
        if text == SWITCH_TO_AI_KEYWORD:
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
            return True

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
    """步骤 3: 已由人工接待的会话 → 跳过"""

    async def execute(self, ctx: ProcessingContext) -> bool:
        if ctx.conversation.handling_type == Conversation.HANDLING_HUMAN:
            ctx.should_stop = True
        return True


class FilterNonCustomerText(PipelineStep):
    """步骤 4: 非客户文本消息（图片、系统消息等）→ 跳过"""

    async def execute(self, ctx: ProcessingContext) -> bool:
        msg = ctx.customer_message
        if msg.sender_type != Conversation.SENDER_CUSTOMER or msg.content_type != "text":
            ctx.should_stop = True
        return True


class BufferAndDeduplicate(PipelineStep):
    """步骤 5: 同会话消息缓冲 + 防抖合并 + 分布式串行锁"""

    async def execute(self, ctx: ProcessingContext) -> bool:
        text = (ctx.customer_message.content or "").strip()
        # 临时跳过缓冲（保留占位，后续可恢复），直接透传
        ctx.customer_text = text
        return True


class RunAssistantOrchestrator(PipelineStep):
    """步骤 6: AssistantService 主编排入口。

    PendingGuard → RecognitionPipeline → Handler 路由 → 回复落库推送。
    processor 仍负责渠道层副作用（落库、WebSocket 广播、转人工）。
    """

    async def execute(self, ctx: ProcessingContext) -> bool:
        bind_usage_context(
            tenant_id=ctx.conversation.tenant_id,
            conversation_id=ctx.conversation.id,
            message_id=ctx.customer_message.id,
        )

        service = _get_assistant_service()
        result = await service.process_message(
            tenant_id=ctx.conversation.tenant_id,
            conversation_id=ctx.conversation.id,
            contact_id=ctx.conversation.contact_id,
            text=ctx.customer_text,
        )

        if not result.reply.strip():
            ctx.should_stop = True
            return True

        # 处理人工转接
        context_update: dict[str, Any] = {}
        if result.handler_result is not None:
            context_update = result.handler_result.context_update or {}

        if context_update.get("requires_human_handoff"):
            reason = (
                context_update.get("pending_human_approval", {}).get("reason", "")
                or "AI 判定需要人工处理"
            )
            await _mark_pending_human(ctx.db, ctx.conversation, reason)

        # 组装 metadata
        metadata = {
            "ai_route": AI_ROUTE_ASSISTANT_SERVICE,
            "scenario_id": result.metadata.get("scenario_id", ""),
            "pending_directive": result.metadata.get("pending_directive", "CLEAR"),
            "resource_trace": result.metadata.get("resource_trace", {}),
            "merged_customer_text": ctx.customer_text,
        }

        logger.info(
            "编排器已处理：conversation=%s scenario=%s directive=%s reply_len=%s",
            ctx.conversation.id,
            result.metadata.get("scenario_id", "?"),
            result.metadata.get("pending_directive", "?"),
            len(result.reply),
        )

        await _create_deliver_and_broadcast_reply_message(
            ctx.db, ctx.conversation, result.reply.strip(),
            sender_type="AI", metadata=metadata,
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
    """AI 消息处理编排入口。按序执行步骤管线，遇到 should_stop 提前终止。

    主链路：Filters → RunAssistantOrchestrator → 落库推送
    """

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
        RunAssistantOrchestrator(),
    ]

    trace_name = f"message.{conversation.tenant_id}"
    async with observe_trace(
        trace_name,
        user_id=str(conversation.contact_id),
        session_id=str(conversation.id),
        tags=["ai"],
        input_data={"content": customer_message.content[:200]},
        tenant_id=conversation.tenant_id,
    ):
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
    """将会话标记为待人工处理，尝试自动分配在线坐席。"""
    from app.models.employee import Employee

    online_agent = await db.scalar(
        select(Employee).where(
            Employee.tenant_id == conversation.tenant_id,
            Employee.deleted_at.is_(None),
            Employee.online_status.in_(["online", "away"]),
        ).order_by(Employee.last_login_at.desc()).limit(1)
    )

    assigned_employee_id = online_agent.id if online_agent is not None else None

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
        from app.services.operations_service import create_notification
        notice_content = (
            f'会话 {conversation.id} 因"{reason}"转入人工处理，已自动分配给坐席 #{assigned_employee_id}。'
            if assigned_employee_id
            else f'会话 {conversation.id} 因"{reason}"转入人工处理，当前无在线坐席，请在坐席上线后及时接管。'
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
    """落库消息 → 渠道出站投递 → WebSocket 广播。"""
    conversation, message = await conversation_service.create_message(
        db,
        conversation.id,
        conversation.tenant_id,
        MessageCreate(sender_type=sender_type, content_type="text", content=content, metadata=metadata),
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


