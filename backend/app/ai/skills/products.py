"""基于统一 Qdrant 向量层的 search_products 技能。"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.product import Product
from app.ai.agent.types import ToolResult
from app.ai.rag.vector_search import VectorDomain, VectorSearchService

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
    """通过分类、商品名或 Qdrant 语义检索启用中的商品。"""
    _ = contact_id
    query_text = str(kwargs.get("query") or kwargs.get("keyword") or kwargs.get("customer_text") or "").strip()
    category_text = str(kwargs.get("category") or "").strip()
    product_name = str(kwargs.get("product_name") or "").strip()

    if product_name:
        logger.info(
            "Skill search_products called with product_name: tenant_id=%s product_name=%s",
            tenant_id,
            product_name,
        )
        products = await _find_products_by_name(db, tenant_id, product_name)
        return _tool_result(products)

    if category_text:
        logger.info(
            "Skill search_products called with category: tenant_id=%s category=%s",
            tenant_id,
            category_text,
        )
        category = await _find_category(db, tenant_id, category_text)
        if category is None:
            return ToolResult(
                ok=True,
                skill_name="search_products",
                result={
                    "products": [],
                    "count": 0,
                    "category": category_text,
                    "message": f"暂时没有找到「{category_text}」这个商品分类，您可以换个品类名再试。",
                },
            )
        result = await db.execute(
            select(Product)
            .where(
                Product.tenant_id == tenant_id,
                Product.is_active.is_(True),
                Product.category_id == category.id,
            )
            .order_by(Product.updated_at.desc(), Product.created_at.desc())
            .limit(MAX_RESULTS)
        )
        products = list(result.scalars().all())
        return _tool_result(products, category=category.name)

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


async def list_product_categories(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    db: AsyncSession,
    **kwargs,
) -> ToolResult:
    """列出租户当前商品分类。"""
    _ = contact_id, kwargs
    logger.info("Skill list_product_categories called: tenant_id=%s", tenant_id)
    result = await db.execute(
        select(Category)
        .where(Category.tenant_id == tenant_id)
        .order_by(Category.sort_order.asc(), Category.created_at.asc())
    )
    categories = [
        {"id": str(category.id), "name": category.name, "parent_id": str(category.parent_id) if category.parent_id else None}
        for category in result.scalars().all()
    ]
    names = "、".join(item["name"] for item in categories) if categories else ""
    message = f"目前有这些商品分类：{names}。您想看哪一类？" if categories else "目前还没有配置商品分类。"
    return ToolResult(
        ok=True,
        skill_name="list_product_categories",
        result={"categories": categories, "count": len(categories), "message": message},
    )


async def get_product_detail(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    db: AsyncSession,
    **kwargs,
) -> ToolResult:
    """查询单个商品详情，优先精确名称，失败后做包含匹配。"""
    _ = contact_id
    product_name = str(kwargs.get("product_name") or kwargs.get("query") or kwargs.get("customer_text") or "").strip()
    logger.info("Skill get_product_detail called: tenant_id=%s product_name=%s", tenant_id, product_name)
    products = await _find_products_by_name(db, tenant_id, product_name, limit=2)
    if not products:
        return ToolResult(
            ok=True,
            skill_name="get_product_detail",
            result={"product": None, "count": 0, "message": "暂时没找到这款商品，您可以提供更完整的型号。"},
        )
    if len(products) > 1:
        return ToolResult(
            ok=True,
            skill_name="get_product_detail",
            result={
                "product": None,
                "products": [_product_payload(product) for product in products],
                "count": len(products),
                "message": "找到多款相近商品，请告诉我具体要看哪一款。",
            },
        )
    product = _product_payload(products[0])
    return ToolResult(
        ok=True,
        skill_name="get_product_detail",
        result={"product": product, "products": [product], "count": 1, "message": _format_product_detail(product)},
    )


def _tool_result(products: list[Product], *, category: str | None = None) -> ToolResult:
    items = [
        _product_payload(product)
        for product in products
    ]
    payload = {"products": items, "count": len(items)}
    if category:
        payload["category"] = category
    return ToolResult(ok=True, skill_name="search_products", result=payload)


def _product_payload(product: Product) -> dict:
    return {
        "id": str(product.id),
        "name": product.name,
        "price": float(product.price) if product.price else None,
        "stock": product.stock,
        "description": product.description or "",
        "category_id": str(product.category_id) if product.category_id is not None else None,
        "qdrant_point_id": product.qdrant_point_id,
    }


async def _find_category(db: AsyncSession, tenant_id: int, category_text: str) -> Category | None:
    exact = await db.scalar(
        select(Category).where(Category.tenant_id == tenant_id, Category.name == category_text).limit(1)
    )
    if exact is not None:
        return exact
    return await db.scalar(
        select(Category)
        .where(Category.tenant_id == tenant_id, Category.name.ilike(f"%{category_text}%"))
        .order_by(Category.sort_order.asc(), Category.created_at.asc())
        .limit(1)
    )


async def _find_products_by_name(
    db: AsyncSession,
    tenant_id: int,
    product_name: str,
    *,
    limit: int = MAX_RESULTS,
) -> list[Product]:
    if not product_name:
        return []
    exact = await db.execute(
        select(Product)
        .where(Product.tenant_id == tenant_id, Product.is_active.is_(True), Product.name == product_name)
        .limit(limit)
    )
    products = list(exact.scalars().all())
    if products:
        return products
    contains = await db.execute(
        select(Product)
        .where(
            Product.tenant_id == tenant_id,
            Product.is_active.is_(True),
            Product.name.ilike(f"%{product_name}%"),
        )
        .order_by(Product.updated_at.desc(), Product.created_at.desc())
        .limit(limit)
    )
    products = list(contains.scalars().all())
    if products:
        return products
    reverse_contains = await db.execute(
        select(Product)
        .where(Product.tenant_id == tenant_id, Product.is_active.is_(True))
        .order_by(Product.updated_at.desc(), Product.created_at.desc())
        .limit(50)
    )
    return [product for product in reverse_contains.scalars().all() if product.name and product.name in product_name][:limit]


def _format_product_detail(product: dict) -> str:
    parts = [f"{product['name']}"]
    if product.get("price") is not None:
        parts.append(f"价格 ¥{float(product['price']):.2f}")
    if product.get("stock") is not None:
        parts.append(f"库存 {product['stock']}")
    if product.get("description"):
        parts.append(str(product["description"]))
    return "，".join(parts)
