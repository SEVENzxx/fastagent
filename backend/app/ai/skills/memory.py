"""remember_info — 从客户消息中 LLM 提取并保存偏好信息。"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales_memory import SalesMemory
from app.ai.agent.types import ToolResult
from app.ai.llm.gateway import LLMClientError, LLMUseCase, complete
from app.ai.llm.prompts.memory import build_memory_extract_messages

async def remember_info(
    *, tenant_id: int, contact_id: int | None = None, db: AsyncSession, **kwargs,
) -> ToolResult:
    """LLM 提取客户偏好 → upsert 到 sales_memory 表。"""
    customer_text = str(kwargs.get("customer_text") or "").strip()
    if not customer_text:
        return ToolResult(ok=False, skill_name="remember_info", error="缺少客户消息文本")
    if contact_id is None:
        return ToolResult(ok=False, skill_name="remember_info", error="缺少客户标识")

    items = await _extract_with_llm(customer_text, tenant_id)
    if not items:
        return ToolResult(ok=True, skill_name="remember_info", result={"saved": [], "message": "暂未识别到特定偏好"})

    saved: list[str] = []
    for item in items:
        key = str(item.get("key", "")).strip()
        value = str(item.get("value", "")).strip()
        if not key or not value:
            continue
        await _upsert_memory(db, tenant_id, contact_id, key, value, customer_text)
        saved.append(f"{key}={value}")

    return ToolResult(ok=True, skill_name="remember_info", result={"saved": saved, "message": f"已记住: {', '.join(saved)}"})


async def _extract_with_llm(text: str, tenant_id: int) -> list[dict]:
    """LLM 提取偏好 key-value，失败返回空列表。"""
    try:
        raw = await complete(
            LLMUseCase.AGENT,
            build_memory_extract_messages(text),
            tenant_id=tenant_id,
            max_tokens=128,
            temperature=0.0,
        )
        return json.loads(raw.strip()).get("items", [])
    except (LLMClientError, json.JSONDecodeError, ValueError):
        return []


async def _upsert_memory(
    db: AsyncSession, tenant_id: int, contact_id: int,
    key: str, value: str, source_text: str,
) -> None:
    """同 (tenant_id, contact_id, key) 覆盖，否则新增。"""
    result = await db.execute(
        select(SalesMemory).where(
            SalesMemory.tenant_id == tenant_id,
            SalesMemory.contact_id == contact_id,
            SalesMemory.key == key,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.value = value
        existing.source = "customer_message"
        existing.metadata_ = {"source_text": source_text}
    else:
        db.add(SalesMemory(
            tenant_id=tenant_id, contact_id=contact_id,
            memory_type="preference", key=key, value=value,
            source="customer_message", metadata_={"source_text": source_text},
        ))
    await db.flush()
