"""订单状态通知服务。"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.websocket_manager import manager
from app.models.conversation import Conversation, Message
from app.models.order import Order
from app.schemas.conversation import MessageCreate
from app.services import conversation_service, outbound_message_service

logger = logging.getLogger(__name__)


async def notify_order_shipped(db: AsyncSession, order: Order) -> Message | None:
    """订单发货后向关联会话推送通知。"""
    if order.conversation_id is None:
        return None

    try:
        conversation = await conversation_service.get_conversation(
            db,
            order.conversation_id,
            order.tenant_id,
        )
        if conversation is None or conversation.contact_id != order.contact_id:
            return None

        _, message = await conversation_service.create_message(
            db,
            conversation.id,
            conversation.tenant_id,
            MessageCreate(
                sender_type=Conversation.SENDER_SYSTEM,
                content_type="text",
                content=_build_shipped_message(order),
                metadata={
                    "event": "order.shipped",
                    "order_id": str(order.id),
                    "source": "order_status_transition",
                },
            ),
        )
        message = await outbound_message_service.deliver_message(db, conversation, message)
        await manager.publish(
            conversation.id,
            {"type": "message.created", "message": _message_payload(message)},
        )
        return message
    except Exception:
        logger.exception("订单发货通知推送失败: order_id=%s", order.id)
        return None


async def notify_order_cancelled(db: AsyncSession, order: Order, reason: str) -> Message | None:
    """订单取消后向关联会话推送通知（含取消原因）。"""
    if order.conversation_id is None:
        return None

    try:
        conversation = await conversation_service.get_conversation(
            db,
            order.conversation_id,
            order.tenant_id,
        )
        if conversation is None or conversation.contact_id != order.contact_id:
            return None

        _, message = await conversation_service.create_message(
            db,
            conversation.id,
            conversation.tenant_id,
            MessageCreate(
                sender_type=Conversation.SENDER_SYSTEM,
                content_type="text",
                content=_build_cancelled_message(order, reason),
                metadata={
                    "event": "order.cancelled",
                    "order_id": str(order.id),
                    "cancel_reason": reason,
                    "source": "order_status_transition",
                },
            ),
        )
        message = await outbound_message_service.deliver_message(db, conversation, message)
        await manager.publish(
            conversation.id,
            {"type": "message.created", "message": _message_payload(message)},
        )
        return message
    except Exception:
        logger.exception("订单取消通知推送失败: order_id=%s", order.id)
        return None


def _build_shipped_message(order: Order) -> str:
    """生成客户侧发货通知文案。"""
    lines = [f"您的订单 #{order.id} 已发货，请注意查收。"]
    item_lines = []
    for item in order.items or []:
        snapshot = item.product_snapshot or {}
        product_name = str(snapshot.get("product_name") or "商品")
        item_lines.append(f"{product_name} × {item.quantity}")
    if item_lines:
        lines.append(f"商品：{'、'.join(item_lines)}")
    return "\n".join(lines)


def _build_cancelled_message(order: Order, reason: str) -> str:
    """生成客户侧订单取消通知文案（含原因）。"""
    lines = [f"您的订单 #{order.id} 已取消。"]
    if reason:
        lines.append(f"原因：{reason}")
    lines.append("如有疑问请联系人工客服。")
    return "\n".join(lines)


def _message_payload(message: Message) -> dict[str, Any]:
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
