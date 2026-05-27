"""渠道消息路由服务。"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.websocket_manager import manager
from app.integrations.wecom import WeComInboundMessage
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.platform import Platform
from app.schemas.conversation import ConversationCreate, MessageCreate
from app.services import conversation_service
from app.services.ai.processor import process_customer_message_with_ai

logger = logging.getLogger(__name__)


def _message_payload(message) -> dict:
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


async def _find_contact_by_wecom_id(
    db: AsyncSession,
    tenant_id: int,
    external_userid: str,
) -> Contact | None:
    return await db.scalar(
        select(Contact).where(
            Contact.tenant_id == tenant_id,
            Contact.external_ids["wecom_external_userid"].astext == external_userid,
        )
    )


async def _get_or_create_contact(
    db: AsyncSession,
    tenant_id: int,
    message: WeComInboundMessage,
) -> Contact:
    contact = await _find_contact_by_wecom_id(db, tenant_id, message.external_userid)
    if contact is not None:
        updated = False
        if message.name and contact.name != message.name:
            contact.name = message.name
            updated = True
        if message.avatar_url and contact.avatar_url != message.avatar_url:
            contact.avatar_url = message.avatar_url
            updated = True
        if updated:
            contact.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(contact)
            logger.info(
                "企业微信联系人已更新：tenant_id=%s contact_id=%s external_userid=%s",
                tenant_id,
                contact.id,
                message.external_userid,
            )
        else:
            logger.info(
                "企业微信联系人已匹配：tenant_id=%s contact_id=%s external_userid=%s",
                tenant_id,
                contact.id,
                message.external_userid,
            )
        return contact

    contact = Contact(
        tenant_id=tenant_id,
        name=message.name or f"企微客户 {message.external_userid[-6:]}",
        avatar_url=message.avatar_url,
        external_ids={"wecom_external_userid": message.external_userid},
        tags=["企业微信"],
    )
    db.add(contact)
    await db.commit()
    await db.refresh(contact)
    logger.info(
        "企业微信联系人已创建：tenant_id=%s contact_id=%s external_userid=%s",
        tenant_id,
        contact.id,
        message.external_userid,
    )
    return contact


async def route_wecom_message(
    db: AsyncSession,
    platform: Platform,
    message: WeComInboundMessage,
) -> tuple[Conversation, object]:
    """把企业微信入站消息路由到联系人、会话和消息。

    路由规则：
    - external_userid 匹配已有联系人；不存在则自动创建联系人。
    - 联系人 assigned_employee_id 作为默认坐席；未分配则会话进入未分配池。
    - 同一联系人复用同一个会话；关闭会话会被重新打开并接着聊。
    - CUSTOMER 消息落库后广播到该会话频道，工作台几秒内可见。
    """
    logger.info(
        "开始路由企业微信消息：tenant_id=%s platform_id=%s external_userid=%s msg_id=%s content_type=%s content_len=%s",
        platform.tenant_id,
        platform.id,
        message.external_userid,
        message.msg_id,
        message.content_type,
        len(message.content or ""),
    )
    contact = await _get_or_create_contact(db, platform.tenant_id, message)
    conversation = await conversation_service.create_conversation(
        db,
        platform.tenant_id,
        ConversationCreate(
            contact_id=contact.id,
            employee_id=contact.assigned_employee_id,
            platform_id=platform.id,
            status="pending_human" if contact.assigned_employee_id else "ai_processing",
            handling_type="human" if contact.assigned_employee_id else "ai_only",
            tags=["企业微信"],
        ),
    )
    logger.info(
        "企业微信会话已解析：tenant_id=%s conversation_id=%s contact_id=%s status=%s handling_type=%s",
        platform.tenant_id,
        conversation.id,
        contact.id,
        conversation.status,
        conversation.handling_type,
    )
    conversation, saved_message = await conversation_service.create_message(
        db,
        conversation.id,
        platform.tenant_id,
        MessageCreate(
            sender_type="CUSTOMER",
            content_type=message.content_type,
            content=message.content,
            metadata={
                "platform": "wecom",
                "external_userid": message.external_userid,
                "msg_id": message.msg_id,
            },
        ),
    )
    logger.info(
        "企业微信客户消息已保存：tenant_id=%s conversation_id=%s message_id=%s msg_id=%s",
        platform.tenant_id,
        conversation.id,
        saved_message.id,
        message.msg_id,
    )
    await manager.publish(
        conversation.id,
        {"type": "message.created", "message": _message_payload(saved_message)},
    )
    await manager.publish(
        conversation.id,
        {
            "type": "conversation.updated",
            "conversationId": str(conversation.id),
        },
    )
    await process_customer_message_with_ai(db, conversation, saved_message)
    logger.info(
        "企业微信消息路由完成：tenant_id=%s conversation_id=%s message_id=%s",
        platform.tenant_id,
        conversation.id,
        saved_message.id,
    )
    return conversation, saved_message
