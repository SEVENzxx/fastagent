"""ProductSkill — 结构化商品 Skill 接口。

接收结构化参数，返回结构化结果。
不接收原始文本，不做意图识别，不自行调用 LLM。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.vector_search import VectorDomain, VectorSearchService
from app.config import settings
from app.models.category import Category
from app.models.product import Product

MAX_RESULTS = 20
_vector_search = VectorSearchService()


class SearchProductParams(BaseModel):
    """商品搜索参数模型。"""
    query_text: str = ""
    product_name: str = ""
    category_text: str = ""
    category_id: int | None = None
    category_ids: list[int] = Field(default_factory=list, description="多分类 ID 列表（用于根分类下钻）")
    min_price: float | None = None
    max_price: float | None = None
    attr_filters: dict[str, Any] = Field(default_factory=dict)
    limit: int = MAX_RESULTS


class ProductSkill:
    """结构化商品 Skill。

    所有方法接收结构化参数，返回 list[dict] 等简单类型。
    """

    @staticmethod
    async def list_categories(
        *,
        db: AsyncSession,
        tenant_id: int,
    ) -> list[dict[str, Any]]:
        """列出商品分类树。"""
        result = await db.execute(
            select(Category)
            .where(Category.tenant_id == tenant_id)
            .order_by(Category.sort_order.asc(), Category.created_at.asc())
        )
        categories = [
            {
                "id": str(c.id),
                "name": c.name,
                "parent_id": str(c.parent_id) if c.parent_id else None,
            }
            for c in result.scalars().all()
        ]
        return _build_category_tree(categories)

    @staticmethod
    async def list_by_category(
        *,
        db: AsyncSession,
        tenant_id: int,
        category_id: int,
        limit: int = MAX_RESULTS,
    ) -> list[dict[str, Any]]:
        """按分类查询商品列表。"""
        result = await db.execute(
            select(Product)
            .where(
                Product.tenant_id == tenant_id,
                Product.is_active.is_(True),
                Product.category_id == category_id,
            )
            .order_by(Product.updated_at.desc(), Product.created_at.desc())
            .limit(limit)
        )
        return [_product_to_dict(p) for p in result.scalars().all()]

    @staticmethod
    async def search_products(
        *,
        db: AsyncSession,
        tenant_id: int,
        params: SearchProductParams,
    ) -> list[dict[str, Any]]:
        """综合搜索商品。"""
        conditions = [Product.tenant_id == tenant_id, Product.is_active.is_(True)]
        if params.category_ids:
            conditions.append(Product.category_id.in_(params.category_ids))
        elif params.category_id is not None:
            conditions.append(Product.category_id == params.category_id)
        if params.min_price is not None:
            conditions.append(Product.price >= params.min_price)
        if params.max_price is not None:
            conditions.append(Product.price <= params.max_price)

        # 属性过滤：通过 JSONB containment 匹配 attrs_json.attr.{key} = value
        # 过滤 null 值，避免 @> 要求数据中也必须是 null
        active_filters = {k: v for k, v in params.attr_filters.items() if v is not None}
        if active_filters:
            attr_obj = {"attr": active_filters}
            conditions.append(Product.attrs_json.op("@>")(attr_obj))

        clean_name = params.product_name.strip()
        if clean_name:
            conditions.append(Product.name.ilike(f"%{clean_name}%"))

        limit = params.limit
        products = list((
            await db.execute(
                select(Product)
                .where(and_(*conditions))
                .order_by(Product.updated_at.desc(), Product.created_at.desc())
                .limit(limit * 5)
            )
        ).scalars().all())

        if not products:
            return []

        vector_query = " ".join(
            part for part in [params.query_text, params.category_text, params.product_name] if part
        ).strip()
        if not vector_query:
            return [_product_to_dict(p) for p in products[:limit]]

        hits = await _vector_search.search_text(
            domain=VectorDomain.PRODUCT,
            tenant_id=tenant_id,
            query=vector_query,
            top_k=max(settings.AI_PRODUCT_VECTOR_TOP_K, limit),
            min_score=settings.AI_PRODUCT_VECTOR_MIN_SCORE,
            filters={"is_active": True},
        )
        vector_order = {
            int(hit.payload["product_id"]): idx
            for idx, hit in enumerate(hits)
            if str(hit.payload.get("product_id", "")).isdigit()
        }
        products.sort(
            key=lambda item: (0, vector_order[item.id])
            if item.id in vector_order
            else (1, 0)
        )
        return [_product_to_dict(p) for p in products[:limit]]

    @staticmethod
    async def get_detail(
        *,
        db: AsyncSession,
        tenant_id: int,
        product_id: int,
    ) -> dict[str, Any] | None:
        """获取单个商品详情。"""
        result = await db.execute(
            select(Product).where(
                Product.id == product_id,
                Product.tenant_id == tenant_id,
                Product.is_active.is_(True),
            )
        )
        product = result.scalar_one_or_none()
        return _product_to_dict(product) if product else None

    @staticmethod
    async def search_by_sku(
        *,
        db: AsyncSession,
        tenant_id: int,
        sku: str,
    ) -> dict[str, Any] | None:
        """按 SKU 精确查询商品。"""
        if not sku:
            return None
        result = await db.execute(
            select(Product).where(
                Product.sku == sku,
                Product.tenant_id == tenant_id,
                Product.is_active.is_(True),
            )
        )
        product = result.scalar_one_or_none()
        return _product_to_dict(product) if product else None

    @staticmethod
    async def batch_get_detail(
        *,
        db: AsyncSession,
        tenant_id: int,
        product_ids: list[int],
    ) -> list[dict[str, Any]]:
        """批量获取商品详情。"""
        if not product_ids:
            return []
        result = await db.execute(
            select(Product).where(
                Product.id.in_(product_ids),
                Product.tenant_id == tenant_id,
                Product.is_active.is_(True),
            )
        )
        products = list(result.scalars().all())
        order = {pid: idx for idx, pid in enumerate(product_ids)}
        products.sort(key=lambda p: order.get(p.id, len(order)))
        return [_product_to_dict(p) for p in products]

    @staticmethod
    async def get_attribute(
        *,
        db: AsyncSession,
        tenant_id: int,
        product_id: int,
        attribute_code: str,
    ) -> dict[str, Any] | None:
        """获取商品指定属性的值。"""
        product = await ProductSkill.get_detail(
            db=db, tenant_id=tenant_id, product_id=product_id,
        )
        if product is None:
            return None
        attrs = product.get("attrs_json") or {}
        inner = attrs.get("attr") if isinstance(attrs.get("attr"), dict) else attrs
        value = inner.get(attribute_code)
        if value is None:
            tags = product.get("feature_tags") or []
            if attribute_code in tags:
                value = attribute_code
        return {
            "product_id": product_id,
            "product_name": product.get("name", ""),
            "attribute_code": attribute_code,
            "value": value,
        }




# ── 内部工具 ──


def _product_to_dict(product: Product) -> dict[str, Any]:
    return {
        "id": str(product.id),
        "name": product.name,
        "sku": product.sku,
        "price": float(product.price) if product.price else None,
        "stock": product.stock,
        "description": product.description or "",
        "category_id": str(product.category_id) if product.category_id is not None else None,
        "qdrant_point_id": product.qdrant_point_id,
        "attrs_json": product.attrs_json,
        "feature_tags": product.feature_tags or [],
        "scenario_tags": product.scenario_tags or [],
        "is_active": product.is_active,
        "tenant_id": product.tenant_id,
    }


def _build_category_tree(
    categories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    children_map: dict[str | None, list[dict]] = {}
    for cat in categories:
        pid = cat["parent_id"]
        children_map.setdefault(pid, []).append(cat)

    def _build(parent_id: str | None) -> list[dict]:
        result: list[dict] = []
        for cat in children_map.get(parent_id, []):
            cat["children"] = _build(cat["id"])
            result.append(cat)
        return result

    return _build(None)


