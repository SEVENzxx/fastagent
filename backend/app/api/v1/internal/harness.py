"""Internal Harness API — development/test only HTTP 对话入口。

仅供开发调试和回归验证使用，**禁止在生产环境暴露**。

安全约束：
  1. 仅在 ``APP_ENV=development`` 或 ``APP_ENV=test`` 时注册（main.py）。
  2. 需要 ``X-Harness-Token`` 请求头，值与配置项 ``settings.HARNESS_API_TOKEN`` 一致。
  3. 所有创建数据带 ``tags=["harness"]`` 和 ``metadata.harness=true`` 标记。
  4. 联系人查找只匹配已有 ``tags=["harness"]`` 的记录，**绝不污染真实客户数据**。
  5. 清理操作同时校验 ``tenant_id`` / ``tags`` / ``harness_run_id``，避免误删。

清理：
  ``DELETE /api/v1/internal/harness/runs/{run_id}``
  删除该 run_id 下创建的全部消息（含 AI 回复）、会话和联系人。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.schemas.conversation import ConversationCreate, MessageCreate
from app.services import conversation_service, platform_service
from app.ai.entry.processor import process_customer_message_with_ai

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/harness", tags=["Internal"])

_ALLOWED_ENVS = ("development", "test")
_RUN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")


def _read_harness_token() -> str:
    """读取 Harness API Token（从 settings.HARNESS_API_TOKEN 读取）。

    注意：运行时修改环境变量不会影响已在处理中的请求，
    但新请求会读到新值。如需热加载，建议用 secrets 卷挂载。
    """
    return settings.HARNESS_API_TOKEN


async def _verify_harness(request: Request) -> None:
    """验证 Harness 请求：

    1. 环境检查 — 生产环境硬拒绝，非 development/test 返回 404。
    2. Token 检查 — X-Harness-Token 必须匹配 HARNESS_API_TOKEN。
    """
    if settings.APP_ENV == "production":
        raise HTTPException(
            status_code=404,
            detail="Internal API not available in production",
        )
    if settings.APP_ENV not in _ALLOWED_ENVS:
        raise HTTPException(
            status_code=404,
            detail="Internal API not available in this environment",
        )
    token = _read_harness_token()
    if not token:
        logger.warning("HARNESS_API_TOKEN 未设置，Harness API 不可用")
        raise HTTPException(
            status_code=503,
            detail="HARNESS_API_TOKEN not configured",
        )
    header_token = request.headers.get("X-Harness-Token")
    if not header_token or header_token != token:
        raise HTTPException(status_code=403, detail="Invalid harness token")


# ── Schemas ──────────────────────────────────────────────────────────────


class HarnessMessageRequest(BaseModel):
    """Harness 消息请求。"""
    tenant_id: int = Field(..., description="租户 ID")
    platform_guid: int = Field(..., description="WeCom 渠道 ID（需是已激活的 wecom 渠道）")
    run_id: str = Field(
        ..., min_length=1, max_length=64,
        pattern=r"^[a-zA-Z0-9._-]+$",
        description="Harness 运行 ID，用于清理和数据标记。仅允许字母、数字、. _ -",
    )
    external_user_id: str = Field(
        ..., min_length=1, max_length=128,
        description="外部用户 ID；同一 case 多轮使用同一 ID 以复用同一 Harness 联系人",
    )
    name: str | None = Field(None, max_length=100, description="客户名称（可选）")
    content: str = Field(..., min_length=1, max_length=4096, description="消息文本内容")


class HarnessMessageResponse(BaseModel):
    """Harness 消息响应。"""
    conversation_id: str
    run_id: str
    reply: str
    status: str


class HarnessCleanupResponse(BaseModel):
    """清理结果。"""
    deleted_messages: int = 0
    deleted_conversations: int = 0
    deleted_contacts: int = 0


# ── 辅助函数 ─────────────────────────────────────────────────────────────


async def _find_or_create_contact(
    db: AsyncSession,
    tenant_id: int,
    external_userid: str,
    name: str | None,
    run_id: str,
) -> Contact:
    """查找或创建 Harness 联系人。

    安全约束：
      - 只匹配 ``tags=["harness"]`` 的已有联系人，**绝不匹配真实客户**。
      - 如果 external_userid 被占用但缺少 harness 标记，创建新联系人。
      - 联系人在 ``external_ids`` 中记录 ``harness_run_id`` 以支持清理。
    """
    contact = await db.scalar(
        select(Contact).where(
            Contact.tenant_id == tenant_id,
            Contact.external_ids["wecom_external_userid"].astext == external_userid,
            Contact.tags.contains(["harness"]),  # 只匹配 Harness 联系人
        )
    )
    if contact is not None:
        return contact

    contact = Contact(
        tenant_id=tenant_id,
        name=name or f"Harness {external_userid[-8:]}",
        external_ids={
            "wecom_external_userid": external_userid,
            "harness_run_id": run_id,
        },
        tags=["harness"],
    )
    db.add(contact)
    await db.commit()
    await db.refresh(contact)
    return contact


async def _find_harness_conversation(
    db: AsyncSession,
    tenant_id: int,
    contact_id: int,
    platform_id: int,
    run_id: str,
) -> Conversation:
    """创建或复用 Harness 会话。

    复用规则：同一 contact 的非关闭会话会被自动复用
    （由 ``conversation_service.create_conversation`` 保证）。

    写入 ``metadata_`` 记录 run_id，支持精确清理。
    """
    conversation = await conversation_service.create_conversation(
        db, tenant_id,
        ConversationCreate(
            contact_id=contact_id,
            platform_id=platform_id,
            status=Conversation.STATUS_AI_PROCESSING,
            handling_type=Conversation.HANDLING_AI_ONLY,
            tags=["harness"],
        ),
    )
    conversation.metadata_ = {
        "harness": True,
        "harness_run_id": run_id,
        "platform": "harness",
    }
    return conversation


# ── 消息发送 ─────────────────────────────────────────────────────────────


@router.post("/messages", response_model=HarnessMessageResponse)
async def harness_send_message(
    body: HarnessMessageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(_verify_harness),
):
    """发送客户消息并触发 AI 处理。

    同一 ``external_user_id`` 在多轮中自动复用同一 Harness 联系人及会话，
    从而实现多轮上下文对话。
    """
    platform = await platform_service.get_active_wecom_by_guid(db, body.platform_guid)
    if platform is None:
        raise HTTPException(status_code=404, detail="渠道不存在或未启用")
    if platform.tenant_id != body.tenant_id:
        raise HTTPException(status_code=403, detail="渠道不属于指定租户")

    contact = await _find_or_create_contact(
        db, body.tenant_id, body.external_user_id, body.name, body.run_id,
    )

    conversation = await _find_harness_conversation(
        db, body.tenant_id, contact.id, platform.id, body.run_id,
    )

    harness_meta: dict[str, Any] = {
        "harness": True,
        "harness_run_id": body.run_id,
        "platform": "harness",
        "external_userid": body.external_user_id,
    }
    conversation, saved_message = await conversation_service.create_message(
        db, conversation.id, body.tenant_id,
        MessageCreate(
            sender_type=Conversation.SENDER_CUSTOMER,
            content_type="text",
            content=body.content,
            metadata=harness_meta,
        ),
    )

    await process_customer_message_with_ai(db, conversation, saved_message)

    ai_message = await db.scalar(
        select(Message).where(
            Message.conversation_id == conversation.id,
            Message.sender_type == "AI",
        ).order_by(Message.created_at.desc()).limit(1)
    )

    return HarnessMessageResponse(
        conversation_id=str(conversation.id),
        run_id=body.run_id,
        reply=ai_message.content if ai_message else "",
        status=conversation.status,
    )


# ── 清理 ──────────────────────────────────────────────────────────────


@router.delete("/runs/{run_id}", response_model=HarnessCleanupResponse)
async def harness_cleanup_run(
    run_id: str,
    tenant_id: int = Query(..., description="租户 ID（必填，防跨租户清理）"),
    platform_id: int | None = Query(None, description="渠道 ID（可选，进一步限定清理范围）"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(_verify_harness),
):
    """清理指定 run_id 下 Harness 创建的测试数据。

    删除策略：
      1. 校验 tenant_id 和 run_id 格式。
      2. 查找 metadata.harness==true AND harness_run_id==run_id 的消息，
         并通过 Conversation JOIN 限制 tenant_id（及可选的 platform_id）。
      3. 获取这些消息所属的会话 ID。
      4. 删除这些会话中的 **所有消息**（含不带 harness 标记的 AI 回复），计数为实际删除数。
      5. 删除 tags=["harness"] 的空会话。
      6. 删除 external_ids.harness_run_id==run_id 且无剩余会话的 Harness 联系人。

    所有删除操作都校验 tenant_id + tags 或 metadata 标记，杜绝跨租户误删。
    """
    # ── 0: 校验 run_id 格式 ──────────────────────────────────────────────
    if not _RUN_ID_PATTERN.match(run_id):
        raise HTTPException(status_code=400, detail="run_id 格式不合法")

    result = HarnessCleanupResponse()

    # ── 1: 查找 Harness 消息（校验 harness 标记 + run_id + tenant_id） ────
    conditions = [
        Message.metadata_["harness"].astext == "true",
        Message.metadata_["harness_run_id"].astext == run_id,
        Conversation.tenant_id == tenant_id,
    ]
    if platform_id is not None:
        conditions.append(Conversation.platform_id == platform_id)

    msg_q = await db.execute(
        select(Message).join(Conversation, Message.conversation_id == Conversation.id).where(*conditions)
    )
    harness_customer_msgs = list(msg_q.scalars().all())
    conv_ids = list({m.conversation_id for m in harness_customer_msgs})

    if not conv_ids:
        logger.info("Harness 清理: run_id=%s tenant_id=%s 无数据", run_id, tenant_id)
        return result

    # ── 2: 确认会话是 Harness 会话（校验 tags + tenant_id） ──────────────
    conv_q = await db.execute(
        select(Conversation).where(
            Conversation.id.in_(conv_ids),
            Conversation.tags.contains(["harness"]),
            Conversation.tenant_id == tenant_id,
        )
    )
    harness_convs = list(conv_q.scalars().all())
    harness_conv_ids = [c.id for c in harness_convs]

    if not harness_conv_ids:
        logger.warning(
            "Harness 清理: run_id=%s tenant_id=%s 找到消息但会话无 harness 标记，跳过",
            run_id, tenant_id,
        )
        return result

    # ── 3: 删除 Harness 会话中的所有消息（含 AI 回复），计数为实际删除数 ──
    deleted_msg_count = 0
    for cid in harness_conv_ids:
        all_msgs = await db.execute(
            select(Message).where(Message.conversation_id == cid)
        )
        msgs = all_msgs.scalars().all()
        deleted_msg_count += len(msgs)
        for msg in msgs:
            await db.delete(msg)
    result.deleted_messages = deleted_msg_count

    # ── 4: 删除 Harness 会话 ─────────────────────────────────────────────
    for conv in harness_convs:
        await db.delete(conv)
    result.deleted_conversations = len(harness_convs)

    await db.commit()

    # ── 5: 清理 Harness 联系人（校验 run_id + tenant_id） ────────────────
    contact_q = await db.execute(
        select(Contact).where(
            Contact.tags.contains(["harness"]),
            Contact.external_ids["harness_run_id"].astext == run_id,
            Contact.tenant_id == tenant_id,
        )
    )
    for contact in contact_q.scalars().all():
        remaining = await db.scalar(
            select(Conversation).where(
                Conversation.contact_id == contact.id,
            ).limit(1)
        )
        if remaining is None:
            await db.delete(contact)
            result.deleted_contacts += 1

    await db.commit()

    logger.info(
        "Harness 清理完成: run_id=%s tenant_id=%s messages=%d conversations=%d contacts=%d",
        run_id, tenant_id, result.deleted_messages, result.deleted_conversations,
        result.deleted_contacts,
    )
    return result
