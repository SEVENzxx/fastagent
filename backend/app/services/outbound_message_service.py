"""工作台中创建的消息的出站投递服务。"""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.wecom_outbound import WeComOutboundClient
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.platform import Platform

logger = logging.getLogger(__name__)


async def deliver_message(db: AsyncSession, conversation: Conversation, message: Message) -> Message:
    """尝试将本地创建的消息发送到对应的外部渠道。"""
    if message.sender_type not in {"AGENT", "AI", "SYSTEM"} or message.content_type != "text":
        logger.info(
            "跳过出站投递：message_id=%s sender_type=%s content_type=%s",
            message.id,
            message.sender_type,
            message.content_type,
        )
        return message
    if conversation.platform_id is None:
        logger.info(
            "跳过出站投递：conversation_id=%s message_id=%s reason=no_platform",
            conversation.id,
            message.id,
        )
        return message

    platform = await db.get(Platform, conversation.platform_id)
    if (
        platform is None
        or platform.tenant_id != conversation.tenant_id
        or platform.type != "wecom"
        or not platform.is_active
    ):
        logger.warning(
            "跳过出站投递：conversation_id=%s message_id=%s platform_id=%s reason=invalid_platform",
            conversation.id,
            message.id,
            conversation.platform_id,
        )
        return message

    contact = await db.get(Contact, conversation.contact_id)
    external_userid = _get_wecom_external_userid(contact)
    logger.info(
        "开始出站投递：tenant_id=%s conversation_id=%s message_id=%s platform_id=%s content_len=%s",
        conversation.tenant_id,
        conversation.id,
        message.id,
        platform.id,
        len(message.content or ""),
    )
    result = await _send_wecom_text(platform, external_userid, message.content or "")
    message.metadata_ = _with_outbound_metadata(message.metadata_ or {}, result)
    await db.commit()
    await db.refresh(message)
    logger.info(
        "出站投递完成：conversation_id=%s message_id=%s platform_id=%s ok=%s",
        conversation.id,
        message.id,
        platform.id,
        result.get("ok"),
    )
    return message


async def _send_wecom_text(platform: Platform, external_userid: str | None, content: str) -> dict:
    """调用企业微信出站接口发送文本消息。"""
    started_at = datetime.now(timezone.utc)
    try:
        if not external_userid:
            raise ValueError("客户联系人缺少 wecom_external_userid 字段")
        result = await WeComOutboundClient(platform.config or {}).send_text(external_userid, content)
        logger.info(
            "企业微信出站消息投递成功，platform_id=%s external_userid=%s content_len=%s",
            platform.id,
            external_userid,
            len(content),
        )
        return {
            "platform": "wecom",
            "ok": True,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "started_at": started_at.isoformat(),
            "result": result,
        }
    except Exception as exc:
        logger.exception("企业微信出站消息投递失败，platform_id=%s", platform.id)
        return {
            "platform": "wecom",
            "ok": False,
            "sent_at": None,
            "started_at": started_at.isoformat(),
            "error": str(exc),
        }


def _get_wecom_external_userid(contact: Contact | None) -> str | None:
    if contact is None or not isinstance(contact.external_ids, dict):
        return None
    value = contact.external_ids.get("wecom_external_userid")
    return str(value).strip() if value else None


def _with_outbound_metadata(metadata: dict, result: dict) -> dict:
    updated = dict(metadata)
    attempts = list(updated.get("outbound_attempts") or [])
    attempts.append(result)
    updated["outbound"] = result
    updated["outbound_attempts"] = attempts[-5:]
    return updated
