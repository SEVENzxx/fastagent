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
    """尝试将本地创建的消息发送到对应的外部渠道。

    ── 处理步骤 ──
      1. 过滤 — 只投递 AGENT / AI / SYSTEM 发出的文本消息
      2. 敏感词风控 — 先检查消息内容是否命中敏感词
      3. block/transfer → 标记 pending_human + 创建通知 + 拦截
      4. 无渠道 → 跳过（纯本地会话，无需投递）
      5. 查渠道配置 + 联系人 external_userid
      6. 调用渠道出站接口（企微 send_text）
      7. 更新消息 metadata（出站结果），提交
    """

    # ── 1: 过滤 — 只投递坐席/AI/系统文本消息 ──
    if message.sender_type not in {Conversation.SENDER_AGENT, Conversation.SENDER_AI, Conversation.SENDER_SYSTEM} or message.content_type != "text":
        return message

    # ── 2: 敏感词风控 ──
    from app.services import operations_service
    sensitive = await operations_service.evaluate_sensitive_text(db, conversation.tenant_id, message.content or "")

    # ── 3: 命中 → block → 拦截并转人工；warn → 记录但不拦截 ──
    if sensitive["action"]:
        metadata = dict(message.metadata_ or {})
        metadata["sensitive_word_check"] = sensitive
        message.metadata_ = metadata
        await operations_service.record_audit(
            db,
            action="sensitive_word_hit",
            resource_type="message",
            tenant_id=conversation.tenant_id,
            resource_id=message.id,
            details=sensitive,
            commit=False,
        )
        if sensitive["action"] in {"block", "transfer"}:
            conversation.status = Conversation.STATUS_PENDING_HUMAN
            conversation.handling_type = Conversation.HANDLING_HUMAN
            conversation.is_transferred = True
            conversation.transfer_reason = "敏感词风控触发"
            metadata["outbound"] = {
                "ok": False,
                "blocked": True,
                "reason": "sensitive_word",
                "action": sensitive["action"],
            }
            await operations_service.create_notification(
                db,
                tenant_id=conversation.tenant_id,
                type="sensitive_word",
                level="error" if sensitive["action"] == "block" else "warning",
                title="消息触发敏感词风控",
                content="出站消息已拦截并转入人工处理。",
                resource_type="conversation",
                resource_id=conversation.id,
                metadata=sensitive,
                commit=False,
            )
            await db.commit()
            await db.refresh(message)
            return message
        # warn → 记录但不拦截，继续投递
        await db.commit()
        await db.refresh(message)

    # ── 4: 无渠道 → 跳过 ──
    if conversation.platform_id is None:
        return message

    # ── 5: 查渠道配置 + 校验 ──
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

    # ── 6: 提取联系人 external_userid → 调用企微出站 ──
    contact = await db.get(Contact, conversation.contact_id)
    external_userid = _get_wecom_external_userid(contact)
    result = await _send_wecom_text(platform, external_userid, message.content or "")

    # ── 7: 更新消息 metadata + 提交 ──
    message.metadata_ = _with_outbound_metadata(message.metadata_ or {}, result)
    await db.commit()
    await db.refresh(message)
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
    """从联系人的 external_ids JSONB 字段提取微信 external_userid。"""
    if contact is None or not isinstance(contact.external_ids, dict):
        return None
    value = contact.external_ids.get("wecom_external_userid")
    return str(value).strip() if value else None


def _with_outbound_metadata(metadata: dict, result: dict) -> dict:
    """将出站投递结果写入消息元数据。"""
    updated = dict(metadata)
    attempts = list(updated.get("outbound_attempts") or [])
    attempts.append(result)
    updated["outbound"] = result
    updated["outbound_attempts"] = attempts[-5:]
    return updated
