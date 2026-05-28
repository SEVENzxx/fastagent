"""search_products — 商品搜索（ILIKE，Phase 11 替换为 pgvector）。"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.services.ai.agent.types import ToolResult

logger = logging.getLogger(__name__)

MAX_RESULTS = 5


async def search_products(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    db: AsyncSession,
    **kwargs,
) -> ToolResult:
    """ILIKE 搜索商品，返回匹配结果列表。

    kwargs 中可传入：
      - query: str 搜索关键词
      - category: str 分类名（将来扩展）
    """
    query_text = str(kwargs.get("query") or kwargs.get("keyword") or "").strip()
    if not query_text:
        # 无关键词时返回所有活跃商品
        logger.info(
            "Skill search_products 无搜索词，返回活跃商品列表：tenant_id=%s",
            tenant_id,
        )
        stmt = (
            select(Product)
            .where(Product.tenant_id == tenant_id, Product.is_active.is_(True))
            .limit(MAX_RESULTS)
        )
    else:
        search_pattern = f"%{query_text}%"
        logger.info(
            "Skill search_products 搜索：tenant_id=%s query=%s",
            tenant_id,
            query_text,
        )
        stmt = (
            select(Product)
            .where(
                Product.tenant_id == tenant_id,
                Product.is_active.is_(True),
                (Product.name.ilike(search_pattern) | Product.description.ilike(search_pattern)),
            )
            .limit(MAX_RESULTS)
        )

    result = await db.execute(stmt)
    products = result.scalars().all()

    if not products:
        logger.info("Skill search_products 无匹配结果：tenant_id=%s query=%s", tenant_id, query_text)
        return ToolResult(
            ok=True,
            skill_name="search_products",
            result={"products": [], "count": 0, "message": "未找到匹配的商品"},
        )

    items = [
        {
            "id": str(p.id),
            "name": p.name,
            "price": float(p.price) if p.price else None,
            "stock": p.stock,
            "description": p.description or "",
        }
        for p in products
    ]
    logger.info(
        "Skill search_products 完成：tenant_id=%s count=%s",
        tenant_id,
        len(items),
    )
    return ToolResult(
        ok=True,
        skill_name="search_products",
        result={"products": items, "count": len(items)},
    )
