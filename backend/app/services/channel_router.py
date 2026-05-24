"""渠道消息路由服务。"""

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
    return conversation, saved_message
