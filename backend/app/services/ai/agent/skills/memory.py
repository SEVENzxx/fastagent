"""remember_info — 客户偏好/信息记忆（LLM 动态提取，无硬编码关键词）。"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.integrations.llm_client import LLMClient, LLMClientError
from app.models.sales_memory import SalesMemory
from app.services.ai.agent.types import ToolResult

logger = logging.getLogger(__name__)

# LLM 提取偏好的系统提示词（通用，不绑定任何具体业务词）
_MEMORY_EXTRACT_SYSTEM_PROMPT = """\
你从客户消息中提取值得记住的偏好或信息。

请输出 JSON 格式：
{"items": [{"key": "偏好维度", "value": "偏好值"}, ...], "nothing": false}

规则：
- key 应当是类别级的简洁标签，如 "favorite_flavor"、"budget_range"、"preferred_style"、"delivery_city"
- value 是客户表达的具体偏好内容
- 如果客户消息中没有任何值得记忆的信息，输出 {"items": [], "nothing": true}
- 不要编造信息，只提取客户明确表达的内容
- 不要输出 Markdown 或额外解释"""


async def remember_info(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    db: AsyncSession,
    **kwargs,
) -> ToolResult:
    """从客户消息中提取并保存偏好信息（LLM 动态提取）。"""
    customer_text = str(kwargs.get("customer_text") or "").strip()
    if not customer_text:
        logger.warning("Skill remember_info 无 customer_text：tenant_id=%s", tenant_id)
        return ToolResult(
            ok=False,
            skill_name="remember_info",
            error="缺少客户消息文本",
        )
    if contact_id is None:
        logger.warning("Skill remember_info 无 contact_id：tenant_id=%s", tenant_id)
        return ToolResult(
            ok=False,
            skill_name="remember_info",
            error="缺少客户标识",
        )

    items = await _extract_with_llm(customer_text)
    if not items:
        logger.info(
            "Skill remember_info 未提取到偏好信息：tenant_id=%s text=%s",
            tenant_id,
            customer_text,
        )
        return ToolResult(
            ok=True,
            skill_name="remember_info",
            result={"saved": [], "message": "暂未识别到特定偏好信息"},
        )

    saved: list[str] = []
    for item in items:
        key = str(item.get("key", "")).strip()
        value = str(item.get("value", "")).strip()
        if not key or not value:
            continue
        await _upsert_memory(db, tenant_id, contact_id, key, value, customer_text)
        saved.append(f"{key}={value}")
        logger.info(
            "Skill remember_info 保存记忆：tenant_id=%s contact_id=%s key=%s value=%s",
            tenant_id,
            contact_id,
            key,
            value,
        )

    logger.info(
        "Skill remember_info 完成：tenant_id=%s contact_id=%s saved=%s",
        tenant_id,
        contact_id,
        saved,
    )
    return ToolResult(
        ok=True,
        skill_name="remember_info",
        result={"saved": saved, "message": f"已记住: {', '.join(saved)}"} if saved else {
            "saved": [], "message": "暂未识别到特定偏好信息"
        },
    )


async def _extract_with_llm(text: str) -> list[dict]:
    """调用小模型提取偏好 key-value。"""
    try:
        client = LLMClient()
        raw = await client.complete(
            [
                {"role": "system", "content": _MEMORY_EXTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            model=settings.AI_GENERAL_REPLY_MODEL or settings.AI_LLM_MODEL,
            max_tokens=128,
            temperature=0.0,
        )
        data = json.loads(raw.strip())
        return data.get("items", [])
    except (LLMClientError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Skill remember_info LLM 提取失败：%s", exc)
        return []


async def _upsert_memory(
    db: AsyncSession,
    tenant_id: int,
    contact_id: int,
    key: str,
    value: str,
    source_text: str,
) -> None:
    stmt = select(SalesMemory).where(
        SalesMemory.tenant_id == tenant_id,
        SalesMemory.contact_id == contact_id,
        SalesMemory.key == key,
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.value = value
        existing.source = "customer_message"
        existing.metadata_ = {"source_text": source_text}
    else:
        memory = SalesMemory(
            tenant_id=tenant_id,
            contact_id=contact_id,
            memory_type="preference",
            key=key,
            value=value,
            source="customer_message",
            metadata_={"source_text": source_text},
        )
        db.add(memory)
    await db.flush()
