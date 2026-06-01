"""基于统一 Qdrant 向量层的 search_products 技能。"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.services.ai.agent.types import ToolResult
from app.services.vector_search_service import VectorDomain, VectorSearchService

logger = logging.getLogger(__name__)

MAX_RESULTS = 5
_vector_search = VectorSearchService()


async def search_products(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    db: AsyncSession,
    **kwargs,
) -> ToolResult:
    """通过 Qdrant 语义检索启用中的商品。"""
    _ = contact_id
    query_text = str(kwargs.get("query") or kwargs.get("keyword") or kwargs.get("customer_text") or "").strip()

    if not query_text:
        logger.info("Skill search_products called without query; returning active products: tenant_id=%s", tenant_id)
        result = await db.execute(
            select(Product)
            .where(Product.tenant_id == tenant_id, Product.is_active.is_(True))
            .order_by(Product.updated_at.desc(), Product.created_at.desc())
            .limit(MAX_RESULTS)
        )
        products = list(result.scalars().all())
        return _tool_result(products)

    hits = await _vector_search.search_text(
        domain=VectorDomain.PRODUCT,
        tenant_id=tenant_id,
        query=query_text,
        top_k=MAX_RESULTS,
        min_score=0.55,
        filters={"is_active": True},
    )
    product_ids = [int(hit.payload["product_id"]) for hit in hits if str(hit.payload.get("product_id", "")).isdigit()]
    if not product_ids:
        logger.info("Skill search_products no Qdrant hits: tenant_id=%s query=%s", tenant_id, query_text)
        return ToolResult(
            ok=True,
            skill_name="search_products",
            result={"products": [], "count": 0, "message": "未找到匹配的商品"},
        )

    result = await db.execute(
        select(Product).where(
            Product.tenant_id == tenant_id,
            Product.is_active.is_(True),
            Product.id.in_(product_ids),
        )
    )
    products = list(result.scalars().all())
    order = {product_id: idx for idx, product_id in enumerate(product_ids)}
    products.sort(key=lambda item: order.get(item.id, len(order)))
    logger.info("Skill search_products complete: tenant_id=%s query=%s count=%s", tenant_id, query_text, len(products))
    return _tool_result(products)


def _tool_result(products: list[Product]) -> ToolResult:
    items = [
        {
            "id": str(product.id),
            "name": product.name,
            "price": float(product.price) if product.price else None,
            "stock": product.stock,
            "description": product.description or "",
            "qdrant_point_id": product.qdrant_point_id,
        }
        for product in products
    ]
    return ToolResult(
        ok=True,
        skill_name="search_products",
        result={"products": items, "count": len(items)},
    )
