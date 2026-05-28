"""remember_info — 客户偏好/信息记忆（真实实现，多表联写）。"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales_memory import SalesMemory
from app.services.ai.agent.types import ToolResult

logger = logging.getLogger(__name__)

# 简单关键词→key 映射，后续可扩展为 LLM 提取
KEYWORD_MAP: dict[str, tuple[str, str]] = {
    "酱香": ("favorite_flavor", "酱香型"),
    "浓香": ("favorite_flavor", "浓香型"),
    "清香": ("favorite_flavor", "清香型"),
    "龙井": ("favorite_tea", "龙井"),
    "碧螺春": ("favorite_tea", "碧螺春"),
    "铁观音": ("favorite_tea", "铁观音"),
    "大红袍": ("favorite_tea", "大红袍"),
    "普洱": ("favorite_tea", "普洱茶"),
    "红茶": ("favorite_tea", "红茶"),
    "绿茶": ("favorite_tea", "绿茶"),
    "花茶": ("favorite_tea", "花茶"),
    "预算": ("budget_range", None),
    "价位": ("budget_range", None),
}


async def remember_info(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    db: AsyncSession,
    **kwargs,
) -> ToolResult:
    """从客户消息中提取并保存偏好信息。

    kwargs 中可传入：
      - customer_text: str 客户原始消息
    """
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

    saved: list[str] = []
    for keyword, (mem_key, mem_value) in KEYWORD_MAP.items():
        if keyword in customer_text:
            value = mem_value or customer_text
            await _upsert_memory(db, tenant_id, contact_id, mem_key, value, customer_text)
            saved.append(f"{mem_key}={value}")
            logger.info(
                "Skill remember_info 保存记忆：tenant_id=%s contact_id=%s key=%s value=%s",
                tenant_id,
                contact_id,
                mem_key,
                value,
            )

    if not saved:
        logger.info(
            "Skill remember_info 未识别到已知偏好关键词：tenant_id=%s text=%s",
            tenant_id,
            customer_text,
        )
        return ToolResult(
            ok=True,
            skill_name="remember_info",
            result={"saved": [], "message": "暂未识别到特定偏好信息"},
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
        result={"saved": saved, "message": f"已记住: {', '.join(saved)}"},
    )


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
