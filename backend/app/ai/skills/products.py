"""基于统一 Qdrant 向量层的 search_products 技能。"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.category import Category
from app.models.product import Product
from app.ai.agent.types import ToolResult
from app.ai.rag.vector_search import VectorDomain, VectorSearchService

logger = logging.getLogger(__name__)

MAX_RESULTS = 20
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
    category_text = _normalize_category_text(category_text)
    product_name = str(kwargs.get("product_name") or "").strip()

    if product_name:
        logger.info(
            "商品搜索技能按商品名查询：tenant_id=%s product_name=%s",
            tenant_id,
            product_name,
        )
        products = await _find_products_by_name(db, tenant_id, product_name)
        return _tool_result(products)

    # 分类查询：直接用 Qdrant 语义搜索，商品已索引 category_path，效果优于 DB WHERE 过滤
    if category_text:
        logger.info("商品搜索技能按分类向量搜索：tenant_id=%s category=%s", tenant_id, category_text)
        hits = await _vector_search.search_text(
            domain=VectorDomain.PRODUCT,
            tenant_id=tenant_id,
            query=category_text,
            top_k=settings.AI_PRODUCT_VECTOR_TOP_K,
            min_score=settings.AI_PRODUCT_VECTOR_MIN_SCORE,
            filters={"is_active": True},
        )
        logger.info(
            "商品搜索向量召回：tenant_id=%s category=%s candidates=%s top_score=%s",
            tenant_id, category_text, len(hits), hits[0].score if hits else 0,
        )
        if not hits:
            return ToolResult(
                ok=True, skill_name="search_products",
                result={"products": [], "count": 0, "category": category_text,
                        "message": f"暂时没有找到「{category_text}」相关商品，您可以换个品类名再试。"},
            )
        products = await _load_products_by_ids(db, tenant_id, [int(h.payload["product_id"]) for h in hits if h.payload.get("product_id")])
        return _tool_result(products, category=category_text)

    if not query_text:
        logger.info("商品搜索技能未传查询条件，返回上架商品：tenant_id=%s", tenant_id)
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
        top_k=settings.AI_PRODUCT_VECTOR_TOP_K,
        min_score=settings.AI_PRODUCT_VECTOR_MIN_SCORE,
        filters={"is_active": True},
    )
    logger.info(
        "商品搜索向量召回：tenant_id=%s query=%s top_k=%s min_score=%s candidates=%s top_score=%s",
        tenant_id,
        query_text[:80],
        settings.AI_PRODUCT_VECTOR_TOP_K,
        settings.AI_PRODUCT_VECTOR_MIN_SCORE,
        len(hits),
        hits[0].score if hits else None,
    )
    product_ids = [int(hit.payload["product_id"]) for hit in hits if str(hit.payload.get("product_id", "")).isdigit()]
    if not product_ids:
        logger.info("商品搜索技能未命中向量结果：tenant_id=%s query=%s", tenant_id, query_text)
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
    logger.info("商品搜索技能完成：tenant_id=%s query=%s count=%s", tenant_id, query_text, len(products))
    return _tool_result(products)


async def list_product_categories(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    db: AsyncSession,
    **kwargs,
) -> ToolResult:
    """列出当前商品分类（以树形结构展示完整层级路径）。"""
    _ = contact_id, kwargs
    logger.info("商品分类技能查询分类列表：tenant_id=%s", tenant_id)
    result = await db.execute(
        select(Category)
        .where(Category.tenant_id == tenant_id)
        .order_by(Category.sort_order.asc(), Category.created_at.asc())
    )
    categories = [
        {"id": str(c.id), "name": c.name, "parent_id": str(c.parent_id) if c.parent_id else None}
        for c in result.scalars().all()
    ]

    # 构建父子映射，生成消息文本时展示完整层级路径
    children_map: dict[str | None, list[dict]] = {}
    for cat in categories:
        pid = cat["parent_id"]
        children_map.setdefault(pid, []).append(cat)

    lines: list[str] = []
    def render_tree(parent_id: str | None, depth: int = 0) -> None:
        for cat in children_map.get(parent_id, []):
            prefix = "  " * depth + ("└ " if depth > 0 else "")
            lines.append(f"{prefix}{cat['name']}")
            render_tree(cat["id"], depth + 1)

    render_tree(None)  # 从根分类开始渲染
    tree_text = "\n".join(lines)
    message = f"目前商品分类如下：\n{tree_text}\n您想看哪一类？" if lines else "目前还没有配置商品分类。"

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
    logger.info("商品详情技能查询商品：tenant_id=%s product_name=%s", tenant_id, product_name)
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


async def _load_products_by_ids(db: AsyncSession, tenant_id: int, product_ids: list[int]) -> list[Product]:
    """根据 product_id 列表从 DB 批量加载 Product 对象，保持 Qdrant 排序。"""
    if not product_ids:
        return []
    result = await db.execute(
        select(Product).where(
            Product.tenant_id == tenant_id,
            Product.id.in_(product_ids),
            Product.is_active.is_(True),
        )
    )
    products = list(result.scalars().all())
    # 按 Qdrant 返回的顺序重新排列
    order = {pid: idx for idx, pid in enumerate(product_ids)}
    products.sort(key=lambda p: order.get(p.id, len(order)))
    return products


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
        "sku": product.sku,
        "price": float(product.price) if product.price else None,
        "stock": product.stock,
        "description": product.description or "",
        "category_id": str(product.category_id) if product.category_id is not None else None,
        "qdrant_point_id": product.qdrant_point_id,
    }


async def _find_category(db: AsyncSession, tenant_id: int, category_text: str) -> Category | None:
    category_text = _normalize_category_text(category_text)
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


def _normalize_category_text(value: str) -> str:
    """仅做通用文本清理，不内置任何行业品类别名。

    SaaS 场景下，任何行业品类别名都应来自商家维护的分类、商品名称、SKU、
    别名或后续向量召回结果，不能写死在平台代码里。
    """

    text = value.strip()
    return text


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
