"""Web Test Chat — AI 客服 web 渠道模拟接口。

用于测试调试，仅在 development/test 环境注册。
无认证要求，通过 phone + nickname 识别客户。
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.database import get_db
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.schemas.conversation import ConversationCreate, MessageCreate
from app.services import conversation_service
from app.ai.entry.processor import process_customer_message_with_ai
from fastapi import APIRouter, Depends

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/channels/web-test", tags=["Web Test"])


class WebTestChatRequest(BaseModel):
    tenant_id: int = Field(..., description="租户 ID")
    phone: str = Field(..., description="手机号码")
    nickname: str = Field(..., description="客户昵称")
    text: str = Field(..., min_length=1, description="消息内容")


class WebTestChatResponse(BaseModel):
    reply: str = Field(description="AI 回复内容")
    conversation_id: int = Field(description="会话 ID")
    contact_id: int = Field(description="联系人 ID")
    resource_trace: dict | None = Field(None, description="资源调用轨迹")


@router.post("/chat", response_model=WebTestChatResponse)
async def web_test_chat(
    req: WebTestChatRequest,
    db: AsyncSession = Depends(get_db),
) -> WebTestChatResponse:
    """Web 渠道模拟：发送消息并获取 AI 回复。

    1. 按 phone 查找或创建联系人
    2. 创建或复用会话
    3. 写入客户消息 → AI 处理
    4. 返回 AI 回复
    """
    # ── 1. 查找或创建联系人 ──
    contact = await db.scalar(
        select(Contact).where(
            Contact.tenant_id == req.tenant_id,
            Contact.phone == req.phone,
        )
    )
    if contact is None:
        contact = Contact(
            tenant_id=req.tenant_id,
            name=req.nickname,
            phone=req.phone,
            tags=["web_test"],
            external_ids={"channel": "web_test"},
        )
        db.add(contact)
        await db.commit()
        await db.refresh(contact)
    elif contact.name != req.nickname:
        contact.name = req.nickname
        await db.commit()

    # ── 2. 复用或创建会话 ──
    conversation = await conversation_service.create_conversation(
        db,
        req.tenant_id,
        ConversationCreate(
            contact_id=contact.id,
            status=Conversation.STATUS_AI_PROCESSING,
            handling_type=Conversation.HANDLING_AI_ONLY,
            tags=["web_test"],
        ),
    )

    # ── 3. 写入客户消息 ──
    _, customer_message = await conversation_service.create_message(
        db,
        conversation.id,
        req.tenant_id,
        MessageCreate(
            sender_type=Conversation.SENDER_CUSTOMER,
            content_type="text",
            content=req.text,
            metadata={"channel": "web_test", "phone": req.phone},
        ),
    )

    # ── 4. AI 处理 ──
    await process_customer_message_with_ai(db, conversation, customer_message)

    # ── 5. 获取 AI 回复 ──
    ai_message = await db.scalar(
        select(Message).where(
            Message.conversation_id == conversation.id,
            Message.sender_type == Conversation.SENDER_AI,
        ).order_by(Message.created_at.desc()).limit(1)
    )

    reply = ai_message.content if ai_message else "（AI 未返回回复）"

    resource_trace = None
    if ai_message and ai_message.metadata_:
        resource_trace = ai_message.metadata_.get("resource_trace")

    return WebTestChatResponse(
        reply=reply,
        conversation_id=conversation.id,
        contact_id=contact.id,
        resource_trace=resource_trace,
    )
