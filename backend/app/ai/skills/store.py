"""get_store_showcase — 品牌/店铺介绍（从 Tenant 表读取）。"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent.types import ToolResult
from app.ai.tenant_config import get_store_showcase as get_tenant_showcase

logger = logging.getLogger(__name__)


async def get_store_showcase(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    db: AsyncSession | None = None,
    **kwargs,
) -> ToolResult:
    """返回店铺品牌介绍（优先读 Tenant.store_showcase，兜底通用介绍）。"""
    logger.info(
        "Skill get_store_showcase 被调用：tenant_id=%s contact_id=%s",
        tenant_id,
        contact_id,
    )
    showcase = None
    if db is not None:
        try:
            showcase = await get_tenant_showcase(db, tenant_id)
        except Exception as exc:
            logger.warning("Skill get_store_showcase 读取租户配置失败：%s — 使用默认", exc)
    if not showcase:
        from app.ai.tenant_config import DEFAULT_STORE_SHOWCASE
        showcase = DEFAULT_STORE_SHOWCASE
    return ToolResult(ok=True, skill_name="get_store_showcase", result=showcase)
