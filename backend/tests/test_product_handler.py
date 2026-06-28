"""ProductHandler 单元测试。

覆盖 9 个核心场景 + 边界：
  1. product.catalog 返回分类列表回复
  2. product.filter_search 搜索并更新 product_candidates
  3. product.detail 精确匹配 → ProductReferenceResolver → get_detail
  4. product.detail 多候选 → SessionContext 候选 + clarify 追问
  6. product.compare 第一款和第二款 → batch_get_detail
  7. product.compare 和第三款又有什么区别 → compare_base_product_id 延续
  8. product.attribute_query 这个是否防水 → last_focus_product_id
  9. 下架/跨租户商品返回已下架提示
     + 边界：未实现场景返回"开发中"
"""
from __future__ import annotations

from typing import Any

import pytest

from app.ai.components.product_reference_resolver import (
    ProductCandidate,
    ProductReferenceResolver,
    ProductReferenceResult,
)
from app.ai.context.pending_state import PendingDirective
from app.ai.handlers.base import HandlerResult
from app.ai.handlers.product import ProductHandler
from app.ai.recognition.types import ScenarioDecision
from app.ai.reply_builders.product import ProductReplyBuilder
from app.ai.context.session_context import SessionContext


# ══════════════════════════════════════════════
# Fake ProductSkill
# ══════════════════════════════════════════════


class FakeProductSkill:
    """内存 ProductSkill，不依赖数据库。"""

    products: dict[int, dict[str, Any]] = {}
    categories: list[dict[str, Any]] = []
    call_log: list[dict[str, Any]] = []

    @classmethod
    def reset(cls) -> None:
        cls.products = {}
        cls.categories = []
        cls.call_log = []

    @classmethod
    def add_product(cls, product_id: int, **overrides: Any) -> None:
        defaults: dict[str, Any] = {
            "id": str(product_id),
            "name": f"产品{product_id}",
            "sku": f"SKU{product_id:04d}",
            "price": 99.99,
            "stock": 10,
            "description": f"产品{product_id}的描述",
            "category_id": None,
            "qdrant_point_id": None,
            "attrs_json": {},
            "feature_tags": [],
            "scenario_tags": [],
            "is_active": True,
            "tenant_id": 1,
        }
        defaults.update(overrides)
        cls.products[product_id] = defaults

    @classmethod
    def add_category(cls, **overrides: Any) -> None:
        defaults: dict[str, Any] = {
            "id": str(len(cls.categories) + 1),
            "name": f"分类{len(cls.categories) + 1}",
            "parent_id": None,
        }
        defaults.update(overrides)
        cls.categories.append(defaults)

    @staticmethod
    async def list_categories(
        *,
        db: Any,
        tenant_id: int,
    ) -> list[dict[str, Any]]:
        FakeProductSkill.call_log.append({"method": "list_categories", "tenant_id": tenant_id})
        return FakeProductSkill.categories

    @staticmethod
    async def search_products(
        *,
        db: Any,
        tenant_id: int,
        query_text: str = "",
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        FakeProductSkill.call_log.append({
            "method": "search_products",
            "tenant_id": tenant_id,
            "query_text": query_text,
        })
        results = [
            p
            for p in FakeProductSkill.products.values()
            if p["is_active"] and p["tenant_id"] == tenant_id
        ]
        if query_text:
            q = query_text.lower()
            results = [p for p in results if q in p["name"].lower()]
        return results[:20]

    @staticmethod
    async def get_detail(
        *,
        db: Any,
        tenant_id: int,
        product_id: int,
    ) -> dict[str, Any] | None:
        FakeProductSkill.call_log.append({
            "method": "get_detail",
            "product_id": product_id,
            "tenant_id": tenant_id,
        })
        p = FakeProductSkill.products.get(product_id)
        if p is None:
            return None
        if p["tenant_id"] != tenant_id or not p["is_active"]:
            return None
        return p

    @staticmethod
    async def batch_get_detail(
        *,
        db: Any,
        tenant_id: int,
        product_ids: list[int],
    ) -> list[dict[str, Any]]:
        FakeProductSkill.call_log.append({
            "method": "batch_get_detail",
            "product_ids": product_ids,
            "tenant_id": tenant_id,
        })
        results: list[dict[str, Any]] = []
        for pid in product_ids:
            p = FakeProductSkill.products.get(pid)
            if p and p["tenant_id"] == tenant_id and p["is_active"]:
                results.append(p)
        return results

    @staticmethod
    async def search_by_sku(
        *,
        db: Any,
        tenant_id: int,
        sku: str,
    ) -> dict[str, Any] | None:
        FakeProductSkill.call_log.append({
            "method": "search_by_sku",
            "sku": sku,
            "tenant_id": tenant_id,
        })
        if not sku:
            return None
        for p in FakeProductSkill.products.values():
            if p.get("sku") == sku and p["tenant_id"] == tenant_id and p["is_active"]:
                return p
        return None

    @staticmethod
    async def get_attribute(
        *,
        db: Any,
        tenant_id: int,
        product_id: int,
        attribute_code: str,
    ) -> dict[str, Any] | None:
        FakeProductSkill.call_log.append({
            "method": "get_attribute",
            "product_id": product_id,
            "attribute_code": attribute_code,
            "tenant_id": tenant_id,
        })
        p = FakeProductSkill.products.get(product_id)
        if p is None or p["tenant_id"] != tenant_id or not p["is_active"]:
            return None
        attrs = p.get("attrs_json") or {}
        inner = attrs.get("attr") if isinstance(attrs.get("attr"), dict) else attrs
        value = inner.get(attribute_code)
        if value is None:
            tags = p.get("feature_tags") or []
            if attribute_code in tags:
                value = attribute_code
        return {
            "product_id": product_id,
            "product_name": p.get("name", ""),
            "attribute_code": attribute_code,
            "value": value,
        }


# ══════════════════════════════════════════════
# Fake Resolver
# ══════════════════════════════════════════════


class FakeResolver(ProductReferenceResolver):
    """可控的 Fake Resolver，不依赖真实网关。"""

    def __init__(
        self,
        default_result: ProductReferenceResult | None = None,
    ) -> None:
        self._default_result = default_result or ProductReferenceResult(
            resolved=False,
            need_clarification=True,
            reason="fake default: 未配置解析结果",
        )
        self._results: dict[str, ProductReferenceResult] = {}
        self.resolve_calls: list[tuple[str, dict[str, Any], Any, int]] = []

    # ── 注意：FakeResolver 不是通过 ProductLookupGateway 实现的，
    # 而是直接从 _results 字典返回匹配项。因此此处不需要实现任何
    # ProductLookupGateway 抽象方法，且没有 gateway 参数。

    def set_result(self, text: str, result: ProductReferenceResult) -> None:
        """按输入文本精确匹配返回结果。"""
        self._results[text] = result

    def set_default(self, result: ProductReferenceResult) -> None:
        self._default_result = result

    async def resolve(
        self,
        text: str,
        entities: dict[str, Any],
        context: Any,
        tenant_id: int,
    ) -> ProductReferenceResult:
        self.resolve_calls.append((text, entities, context, tenant_id))
        return self._results.get(text, self._default_result)


# ══════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════


def make_decision(scenario_id: str, **extra: Any) -> ScenarioDecision:
    """构造 ScenarioDecision，entities 中包含 raw_text。"""
    entities: dict[str, Any] = {"raw_text": extra.pop("text", "")}
    entities.update(extra)
    return ScenarioDecision(
        scenario_id=scenario_id,
        confidence=1.0,
        entities=entities,
    )


def make_context(**overrides: Any) -> SessionContext:
    """构造 SessionContext。"""
    defaults: dict[str, Any] = {
        "tenant_id": 1,
        "conversation_id": 1,
    }
    defaults.update(overrides)
    return SessionContext(**defaults)



# ══════════════════════════════════════════════
# 1. product.catalog
# ══════════════════════════════════════════════


class TestProductCatalog:
    """商品分类浏览。"""

    @pytest.mark.asyncio
    async def test_catalog_returns_reply(self) -> None:
        FakeProductSkill.reset()
        FakeProductSkill.add_category(name="电子产品")
        FakeProductSkill.add_category(name="家居用品")

        handler = ProductHandler(
            skill=FakeProductSkill,
            resolver=FakeResolver(),
        )
        ctx = make_context()
        decision = make_decision("product.catalog")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.catalog"
        assert "商品分类" in result.reply
        assert result.pending_directive == PendingDirective.CLEAR

    @pytest.mark.asyncio
    async def test_catalog_empty(self) -> None:
        """无分类时也能正常回复。"""
        FakeProductSkill.reset()

        handler = ProductHandler(
            skill=FakeProductSkill,
            resolver=FakeResolver(),
        )
        ctx = make_context()
        decision = make_decision("product.catalog")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.catalog"
        assert result.reply
        assert result.pending_directive == PendingDirective.CLEAR


# ══════════════════════════════════════════════
# 2. product.filter_search
# ══════════════════════════════════════════════


class TestProductFilterSearch:
    """商品筛选搜索。"""

    @pytest.mark.asyncio
    async def test_filter_search_returns_products(self) -> None:
        FakeProductSkill.reset()
        FakeProductSkill.add_product(101, name="无线耳机", price=199.0)
        FakeProductSkill.add_product(102, name="蓝牙耳机", price=299.0)

        handler = ProductHandler(
            skill=FakeProductSkill,
            resolver=FakeResolver(),
        )
        ctx = make_context()
        decision = make_decision("product.filter_search", text="耳机")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.filter_search"
        assert result.pending_directive == PendingDirective.CLEAR
        # 生成候选
        assert "product_candidates" in result.context_update
        assert len(result.context_update["product_candidates"]) == 2
        # 回复中包含商品名
        assert "无线耳机" in result.reply or "1." in result.reply

    @pytest.mark.asyncio
    async def test_filter_search_no_results(self) -> None:
        """无结果时回复 no_results。"""
        FakeProductSkill.reset()

        handler = ProductHandler(
            skill=FakeProductSkill,
            resolver=FakeResolver(),
        )
        ctx = make_context()
        decision = make_decision("product.filter_search", text="不存在的产品")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.filter_search"
        assert "没有" in result.reply or "暂时" in result.reply
        assert result.pending_directive == PendingDirective.CLEAR

    @pytest.mark.asyncio
    async def test_filter_search_updates_context(self) -> None:
        """context_update 包含 last_intent。"""
        FakeProductSkill.reset()
        FakeProductSkill.add_product(101, name="测试商品")

        handler = ProductHandler(
            skill=FakeProductSkill,
            resolver=FakeResolver(),
        )
        ctx = make_context()
        decision = make_decision("product.filter_search", text="测试")

        result = await handler.execute(decision, ctx)

        assert result.context_update.get("last_intent") == "product.filter_search"
        # 未设置 last_product_id —— 搜索不生成焦点产品
        assert result.context_update.get("last_product_id") is None


# ══════════════════════════════════════════════
# 3. product.detail
# ══════════════════════════════════════════════


class TestProductDetail:
    """商品详情。"""

    @pytest.mark.asyncio
    async def test_detail_exact_match(self) -> None:
        """精确产品名 → resolver 解析 → get_detail → 回复。"""
        FakeProductSkill.reset()
        FakeProductSkill.add_product(101, name="无线蓝牙耳机", price=199.0)

        resolver = FakeResolver()
        resolver.set_result(
            "无线蓝牙耳机",
            ProductReferenceResult(
                resolved=True,
                product_id=101,
                product_name="无线蓝牙耳机",
                candidates=[
                    ProductCandidate(index=1, product_id=101, product_name="无线蓝牙耳机"),
                ],
                reason="名称匹配",
            ),
        )
        handler = ProductHandler(skill=FakeProductSkill, resolver=resolver)
        ctx = make_context()
        decision = make_decision("product.detail", text="无线蓝牙耳机")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.detail"
        assert "无线蓝牙耳机" in result.reply
        assert result.pending_directive == PendingDirective.CLEAR
        assert result.context_update.get("last_product_id") == "101"
        assert result.context_update.get("last_intent") == "product.detail"

    @pytest.mark.asyncio
    async def test_detail_multi_candidate_updates_context(self) -> None:
        """多候选 → CLEAR + 写入 SessionContext 候选。"""
        FakeProductSkill.reset()
        FakeProductSkill.add_product(101, name="Tab 11 平板电脑")
        FakeProductSkill.add_product(102, name="Tab 11 Pro 平板电脑")

        resolver = FakeResolver()
        resolver.set_result(
            "Tab 11",
            ProductReferenceResult(
                resolved=False,
                need_clarification=True,
                candidates=[
                    ProductCandidate(index=1, product_id=101, product_name="Tab 11 平板电脑"),
                    ProductCandidate(index=2, product_id=102, product_name="Tab 11 Pro 平板电脑"),
                ],
                reason="模糊匹配到 2 个候选",
            ),
        )
        handler = ProductHandler(skill=FakeProductSkill, resolver=resolver)
        ctx = make_context()
        decision = make_decision("product.detail", text="Tab 11")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.detail"
        assert result.pending_directive == PendingDirective.CLEAR
        assert result.pending_state is None
        assert len(result.context_update.get("product_candidates", [])) == 2
        assert len(result.context_update.get("last_visible_products", [])) == 2
        assert "以下是为您找到的商品" in result.reply
        assert "1." in result.reply
        assert "Tab 11 平板电脑" in result.reply or "Tab 11 Pro 平板电脑" in result.reply

    @pytest.mark.asyncio
    async def test_detail_no_match(self) -> None:
        """无匹配 → reply 返回 resolver 的 reason 文本。"""
        FakeProductSkill.reset()

        resolver = FakeResolver()
        resolver.set_default(
            ProductReferenceResult(
                resolved=False,
                need_clarification=True,
                reason="未找到匹配「不存在的产品」的产品",
            ),
        )
        handler = ProductHandler(skill=FakeProductSkill, resolver=resolver)
        ctx = make_context()
        decision = make_decision("product.detail", text="不存在的产品")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.detail"
        assert result.reply  # 返回了 reason 文本
        assert result.pending_directive == PendingDirective.CLEAR


# ══════════════════════════════════════════════
# 5. product.compare
# ══════════════════════════════════════════════


class TestProductCompare:
    """商品对比。"""

    @pytest.mark.asyncio
    async def test_compare_first_and_second(self) -> None:
        """第一款和第二款有什么区别 → batch_get_detail。"""
        FakeProductSkill.reset()
        FakeProductSkill.add_product(101, name="Tab 11 平板电脑", price=1999.0)
        FakeProductSkill.add_product(102, name="Tab 11 Pro 平板电脑", price=2999.0)

        handler = ProductHandler(
            skill=FakeProductSkill,
            resolver=FakeResolver(),
        )
        ctx = make_context(
            product_candidates=[
                {"id": 101, "name": "Tab 11 平板电脑"},
                {"id": 102, "name": "Tab 11 Pro 平板电脑"},
            ],
        )
        decision = make_decision("product.compare", text="第一款和第二款有什么区别")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.compare"
        assert result.pending_directive == PendingDirective.CLEAR
        assert "Tab 11 平板电脑" in result.reply
        assert "Tab 11 Pro 平板电脑" in result.reply
        assert "vs" in result.reply
        # 设置了 compare_base_product_id
        assert result.context_update.get("compare_base_product_id") == "101"
        assert result.context_update.get("last_intent") == "product.compare"

    @pytest.mark.asyncio
    async def test_compare_continuation_vs_third(self) -> None:
        """和第三款又有什么区别 → 使用 compare_base_product_id + resolver 解析。"""
        FakeProductSkill.reset()
        FakeProductSkill.add_product(101, name="Tab 11 平板电脑", price=1999.0)
        FakeProductSkill.add_product(103, name="Galaxy Tab S9", price=3999.0)

        resolver = FakeResolver()
        resolver.set_result(
            "和第三款比",
            ProductReferenceResult(
                resolved=True,
                product_id=103,
                product_name="Galaxy Tab S9",
                candidates=[
                    ProductCandidate(index=3, product_id=103, product_name="Galaxy Tab S9"),
                ],
                reason="对比延续解析",
            ),
        )
        handler = ProductHandler(skill=FakeProductSkill, resolver=resolver)
        ctx = make_context(
            product_candidates=[
                {"id": 101, "name": "Tab 11 平板电脑"},
                {"id": 102, "name": "Tab 11 Pro 平板电脑"},
                {"id": 103, "name": "Galaxy Tab S9"},
            ],
            compare_base_product_id="101",
            last_focus_product_id="101",
        )
        decision = make_decision("product.compare", text="和第三款比")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.compare"
        assert result.pending_directive == PendingDirective.CLEAR
        assert "vs" in result.reply
        assert result.context_update.get("compare_base_product_id") is not None

    @pytest.mark.asyncio
    async def test_compare_continuation_fallback_last_focus(self) -> None:
        """无 compare_base_product_id → fallback last_focus_product_id。"""
        FakeProductSkill.reset()
        FakeProductSkill.add_product(101, name="Tab 11 平板电脑", price=1999.0)
        FakeProductSkill.add_product(103, name="Galaxy Tab S9", price=3999.0)

        resolver = FakeResolver()
        resolver.set_result(
            "和第三款比",
            ProductReferenceResult(
                resolved=True,
                product_id=103,
                product_name="Galaxy Tab S9",
                candidates=[
                    ProductCandidate(index=3, product_id=103, product_name="Galaxy Tab S9"),
                ],
                reason="对比延续解析",
            ),
        )
        handler = ProductHandler(skill=FakeProductSkill, resolver=resolver)
        ctx = make_context(
            product_candidates=[
                {"id": 101, "name": "Tab 11 平板电脑"},
                {"id": 102, "name": "Tab 11 Pro 平板电脑"},
                {"id": 103, "name": "Galaxy Tab S9"},
            ],
            compare_base_product_id=None,
            last_focus_product_id="101",
        )
        decision = make_decision("product.compare", text="和第三款比")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.compare"
        assert result.pending_directive == PendingDirective.CLEAR
        assert "vs" in result.reply

    @pytest.mark.asyncio
    async def test_compare_ordinal_out_of_range(self) -> None:
        """序号超出候选范围 → 提示重新选择。"""
        FakeProductSkill.reset()
        FakeProductSkill.add_product(101, name="产品1")

        handler = ProductHandler(
            skill=FakeProductSkill,
            resolver=FakeResolver(),
        )
        ctx = make_context(
            product_candidates=[{"id": 101, "name": "产品1"}],
        )
        decision = make_decision("product.compare", text="第一款和第五款有什么区别")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.compare"
        assert "超出" in result.reply or "重新" in result.reply
        assert result.pending_directive == PendingDirective.CLEAR

    @pytest.mark.asyncio
    async def test_compare_product_unavailable(self) -> None:
        """对比商品已下架 → 提示。"""
        FakeProductSkill.reset()
        FakeProductSkill.add_product(101, name="产品1")
        # 产品 102 未注册，get_detail 返回 None

        handler = ProductHandler(
            skill=FakeProductSkill,
            resolver=FakeResolver(),
        )
        ctx = make_context(
            product_candidates=[
                {"id": 101, "name": "产品1"},
                {"id": 102, "name": "产品2"},
            ],
        )
        decision = make_decision("product.compare", text="第一款和第二款有什么区别")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.compare"
        assert "下架" in result.reply or "不可见" in result.reply
        assert result.pending_directive == PendingDirective.CLEAR


# ══════════════════════════════════════════════
# 6. product.attribute_query
# ══════════════════════════════════════════════


class TestProductAttributeQuery:
    """商品属性查询。"""

    @pytest.mark.asyncio
    async def test_attribute_query_deixis(self) -> None:
        """'这个是否防水' → last_focus_product_id → resoler 解析 → _attribute_by_id。"""
        FakeProductSkill.reset()
        FakeProductSkill.add_product(301, name="无线蓝牙耳机")

        resolver = FakeResolver()
        resolver.set_result(
            "这个防水吗",
            ProductReferenceResult(
                resolved=True,
                product_id=301,
                product_name="无线蓝牙耳机",
                candidates=[
                    ProductCandidate(index=1, product_id=301, product_name="无线蓝牙耳机"),
                ],
                reason="指代解析：这个",
            ),
        )
        handler = ProductHandler(skill=FakeProductSkill, resolver=resolver)
        ctx = make_context(last_focus_product_id="301")
        decision = make_decision("product.attribute_query", text="这个防水吗")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.attribute_query"
        assert result.pending_directive == PendingDirective.CLEAR
        assert "无线蓝牙耳机" in result.reply

    @pytest.mark.asyncio
    async def test_attribute_query_no_match(self) -> None:
        """未匹配到商品 → 提示提供产品名。"""
        FakeProductSkill.reset()

        resolver = FakeResolver()
        resolver.set_default(
            ProductReferenceResult(
                resolved=False,
                need_clarification=True,
                reason="未找到匹配",
            ),
        )
        handler = ProductHandler(skill=FakeProductSkill, resolver=resolver)
        ctx = make_context()
        decision = make_decision("product.attribute_query", text="不存在的产品")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.attribute_query"
        assert result.reply  # _clarify_result 返回 reason 文本
        assert result.pending_directive == PendingDirective.CLEAR

    @pytest.mark.asyncio
    async def test_attribute_query_multi_candidate_updates_context(self) -> None:
        """多候选 → CLEAR + 写入 SessionContext 候选。"""
        FakeProductSkill.reset()

        resolver = FakeResolver()
        resolver.set_result(
            "Tab 11",
            ProductReferenceResult(
                resolved=False,
                need_clarification=True,
                candidates=[
                    ProductCandidate(index=1, product_id=101, product_name="Tab 11 平板电脑"),
                    ProductCandidate(index=2, product_id=102, product_name="Tab 11 Pro 平板电脑"),
                ],
                reason="模糊匹配到 2 个候选",
            ),
        )
        handler = ProductHandler(skill=FakeProductSkill, resolver=resolver)
        ctx = make_context()
        decision = make_decision("product.attribute_query", text="Tab 11")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.attribute_query"
        assert result.pending_directive == PendingDirective.CLEAR
        assert result.pending_state is None
        assert len(result.context_update.get("product_candidates", [])) == 2


# ══════════════════════════════════════════════
# 7. 下架/跨租户产品
# ══════════════════════════════════════════════


class TestInactiveProduct:
    """下架/跨租户商品不能返回详情。"""

    @pytest.mark.asyncio
    async def test_inactive_product_detail(self) -> None:
        """下架商品 → 已下架提示。"""
        FakeProductSkill.reset()
        FakeProductSkill.add_product(999, name="已下架产品", is_active=False)

        resolver = FakeResolver()
        resolver.set_result(
            "已下架产品",
            ProductReferenceResult(
                resolved=True,
                product_id=999,
                product_name="已下架产品",
                candidates=[
                    ProductCandidate(index=1, product_id=999, product_name="已下架产品"),
                ],
                reason="名称匹配",
            ),
        )
        handler = ProductHandler(skill=FakeProductSkill, resolver=resolver)
        ctx = make_context()
        decision = make_decision("product.detail", text="已下架产品")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.detail"
        assert "下架" in result.reply or "不存在" in result.reply or "未找到" in result.reply
        assert result.pending_directive == PendingDirective.CLEAR

    @pytest.mark.asyncio
    async def test_cross_tenant_product_detail(self) -> None:
        """跨租户商品 → 不存在提示。"""
        FakeProductSkill.reset()
        # 产品属于 tenant_id=1
        FakeProductSkill.add_product(101, name="产品1", tenant_id=1)

        resolver = FakeResolver()
        resolver.set_result(
            "产品1",
            ProductReferenceResult(
                resolved=True,
                product_id=101,
                product_name="产品1",
                candidates=[
                    ProductCandidate(index=1, product_id=101, product_name="产品1"),
                ],
                reason="名称匹配",
            ),
        )
        handler = ProductHandler(skill=FakeProductSkill, resolver=resolver)
        # 当前会话为 tenant_id=2
        ctx = make_context(tenant_id=2)
        decision = make_decision("product.detail", text="产品1")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.detail"
        assert "下架" in result.reply or "不存在" in result.reply or "未找到" in result.reply
        assert result.pending_directive == PendingDirective.CLEAR

    @pytest.mark.asyncio
    async def test_inactive_product_compare(self) -> None:
        """对比中包含已下架商品 → 提示。"""
        FakeProductSkill.reset()
        FakeProductSkill.add_product(101, name="产品1", is_active=False)
        FakeProductSkill.add_product(102, name="产品2")

        handler = ProductHandler(
            skill=FakeProductSkill,
            resolver=FakeResolver(),
        )
        ctx = make_context(
            product_candidates=[
                {"id": 101, "name": "产品1"},
                {"id": 102, "name": "产品2"},
            ],
        )
        decision = make_decision("product.compare", text="第一款和第二款有什么区别")

        result = await handler.execute(decision, ctx)

        # 产品1 不可见，batch_get_detail 只返回 1 个结果
        assert result.scenario_id == "product.compare"
        assert "下架" in result.reply or "不可见" in result.reply
        assert result.pending_directive == PendingDirective.CLEAR


# ══════════════════════════════════════════════
# 8. 未实现场景
# ══════════════════════════════════════════════


class TestUnimplementedScenarios:
    """未实现场景返回"开发中"。"""

    @pytest.mark.asyncio
    async def test_semantic_recommend_no_products(self) -> None:
        """语义推荐无匹配商品时返回推荐提示。"""
        FakeProductSkill.reset()
        handler = ProductHandler(skill=FakeProductSkill, resolver=FakeResolver())
        ctx = make_context()
        decision = make_decision("product.semantic_recommend", text="推荐一款防水耳机")
        result = await handler.execute(decision, ctx)
        # LLM 抽取降级为纯文本搜索，product_candidates 为空 → 推荐提示
        assert "没有找到" in result.reply or "推荐" in result.reply
        assert result.pending_directive == PendingDirective.CLEAR

    @pytest.mark.asyncio
    async def test_semantic_recommend_with_results(self) -> None:
        """语义推荐有匹配商品时返回列表。"""
        FakeProductSkill.reset()
        FakeProductSkill.add_product(101, name="防水耳机", price=199.0)
        handler = ProductHandler(skill=FakeProductSkill, resolver=FakeResolver())
        ctx = make_context()
        decision = make_decision("product.semantic_recommend", text="推荐一款防水耳机")
        result = await handler.execute(decision, ctx)
        assert result.scenario_id == "product.semantic_recommend"
        assert "防水耳机" in result.reply
        assert result.pending_directive == PendingDirective.CLEAR

    @pytest.mark.asyncio
    async def test_sku_query_no_sku(self) -> None:
        """无 SKU 参数时提示输入 SKU。"""
        handler = ProductHandler(skill=FakeProductSkill, resolver=FakeResolver())
        ctx = make_context()
        decision = make_decision("product.sku_query")
        result = await handler.execute(decision, ctx)
        assert "SKU" in result.reply

    @pytest.mark.asyncio
    async def test_sku_query_found(self) -> None:
        """有效 SKU 返回商品详情。"""
        FakeProductSkill.reset()
        FakeProductSkill.add_product(101, name="无线耳机", sku="SKU0101", price=199.0)
        handler = ProductHandler(skill=FakeProductSkill, resolver=FakeResolver())
        ctx = make_context()
        entities: dict[str, Any] = {"raw_text": "SKU0101", "sku": "SKU0101"}
        decision = ScenarioDecision(
            scenario_id="product.sku_query", confidence=1.0, entities=entities,
        )
        result = await handler.execute(decision, ctx)
        assert result.scenario_id == "product.sku_query"
        assert "无线耳机" in result.reply or "SKU0101" in result.reply
        assert result.pending_directive == PendingDirective.CLEAR
        sku_call = next(
            (c for c in FakeProductSkill.call_log if c["method"] == "search_by_sku"), None,
        )
        assert sku_call is not None, "handler 应调用 search_by_sku"
        assert sku_call["sku"] == "SKU0101"

    @pytest.mark.asyncio
    async def test_pagination_sort_no_candidates(self) -> None:
        """无候选时提示搜索商品。"""
        handler = ProductHandler(skill=FakeProductSkill, resolver=FakeResolver())
        ctx = make_context()
        decision = make_decision("product.pagination_sort")
        result = await handler.execute(decision, ctx)
        assert "搜索" in result.reply

    @pytest.mark.asyncio
    async def test_pagination_sort_with_candidates(self) -> None:
        """有候选时按 page 分页返回。"""
        FakeProductSkill.reset()
        for i in range(1, 8):
            FakeProductSkill.add_product(100 + i, name=f"商品{i}", price=float(i * 100))
        handler = ProductHandler(skill=FakeProductSkill, resolver=FakeResolver())
        ctx = make_context(
            product_candidates=[
                {"id": 100 + i, "name": f"商品{i}"} for i in range(1, 8)
            ],
        )
        decision = make_decision("product.pagination_sort", page=2)
        result = await handler.execute(decision, ctx)
        assert result.scenario_id == "product.pagination_sort"
        assert "商品1" in result.reply or "商品" in result.reply
        assert result.pending_directive == PendingDirective.CLEAR

    @pytest.mark.asyncio
    async def test_pagination_sort_from_context_page(self) -> None:
        """从上下文读取当前页码。"""
        FakeProductSkill.reset()
        for i in range(1, 8):
            FakeProductSkill.add_product(100 + i, name=f"商品{i}", price=float(i * 100))
        handler = ProductHandler(skill=FakeProductSkill, resolver=FakeResolver())
        ctx = make_context(
            product_candidates=[
                {"id": 100 + i, "name": f"商品{i}"} for i in range(1, 8)
            ],
            product_page=2,
        )
        # entities 中无 page 参数，使用上下文的 product_page（2）
        decision = make_decision("product.pagination_sort")
        result = await handler.execute(decision, ctx)
        assert result.scenario_id == "product.pagination_sort"
        assert result.reply
        # 上下文更新应包含当前页码
        assert result.context_update.get("product_page") is not None

    @pytest.mark.asyncio
    async def test_unhandled_scenario(self) -> None:
        handler = ProductHandler(skill=FakeProductSkill, resolver=FakeResolver())
        ctx = make_context()
        decision = make_decision("product.unknown")
        result = await handler.execute(decision, ctx)
        assert "开发中" in result.reply


# ══════════════════════════════════════════════
# 9. 边界
# ══════════════════════════════════════════════


class TestProductHandlerEdgeCases:
    """边界情况。"""

    @pytest.mark.asyncio
    async def test_empty_text_falls_back_to_context(self) -> None:
        """raw_text 为空时 fallback 到 ctx.last_user_message。"""
        FakeProductSkill.reset()
        FakeProductSkill.add_product(101, name="测试商品")

        resolver = FakeResolver()
        resolver.set_result(
            "测试商品",
            ProductReferenceResult(
                resolved=True,
                product_id=101,
                product_name="测试商品",
                candidates=[
                    ProductCandidate(index=1, product_id=101, product_name="测试商品"),
                ],
                reason="名称匹配",
            ),
        )
        handler = ProductHandler(skill=FakeProductSkill, resolver=resolver)
        ctx = make_context(last_user_message="测试商品")
        # 构造 decision 时 entities 中无 raw_text
        entities: dict[str, Any] = {}
        decision = ScenarioDecision(
            scenario_id="product.detail",
            confidence=1.0,
            entities=entities,
        )

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.detail"
        assert result.reply
        assert result.pending_directive == PendingDirective.CLEAR

    @pytest.mark.asyncio
    async def test_default_resolver_created_when_not_injected(self) -> None:
        """未注入 resolver 时 _get_resolver 使用默认 resolver。"""
        handler = ProductHandler(skill=FakeProductSkill)  # resolver=None
        ctx = make_context()
        decision = make_decision("product.detail", text="不存在的产品")

        # 默认 resolver 使用无 DB 降级模式，不应抛出异常
        result = await handler.execute(decision, ctx)
        assert result.scenario_id == "product.detail"
        assert result.reply
        assert result.pending_directive == PendingDirective.CLEAR



# ══════════════════════════════════════════════
# 10. 扩展场景验证
# ══════════════════════════════════════════════


class TestProductScenarioDetail:
    """扩展场景验证：断言调用了正确的 Skill 方法。"""

    @pytest.mark.asyncio
    async def test_catalog_calls_list_categories(self) -> None:
        """product.catalog 调用 list_categories 而非返回骨架占位。"""
        FakeProductSkill.reset()
        FakeProductSkill.add_category(name="电子产品")
        FakeProductSkill.add_category(name="家居用品")

        handler = ProductHandler(skill=FakeProductSkill, resolver=FakeResolver())
        ctx = make_context()
        decision = make_decision("product.catalog")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.catalog"
        assert "商品分类" in result.reply
        assert len(FakeProductSkill.call_log) >= 1
        list_call = next(
            (c for c in FakeProductSkill.call_log if c["method"] == "list_categories"),
            None,
        )
        assert list_call is not None, "handler 应调用 list_categories"
        assert list_call["tenant_id"] == 1

    @pytest.mark.asyncio
    async def test_attribute_query_calls_get_attribute(self) -> None:
        """product.attribute_query 传入 attribute_code 时调用 get_attribute。"""
        FakeProductSkill.reset()
        FakeProductSkill.add_product(
            301, name="无线蓝牙耳机",
            attrs_json={"attr": {"防水": "是", "降噪": "支持"}},
        )

        resolver = FakeResolver()
        resolver.set_result(
            "这个防水吗",
            ProductReferenceResult(
                resolved=True,
                product_id=301,
                product_name="无线蓝牙耳机",
                candidates=[
                    ProductCandidate(index=1, product_id=301, product_name="无线蓝牙耳机"),
                ],
                reason="指代解析",
            ),
        )
        handler = ProductHandler(skill=FakeProductSkill, resolver=resolver)
        ctx = make_context(last_focus_product_id="301")
        decision = make_decision(
            "product.attribute_query",
            text="这个防水吗",
            attribute_code="防水",
        )

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.attribute_query"
        assert result.pending_directive == PendingDirective.CLEAR
        get_attr_call = next(
            (c for c in FakeProductSkill.call_log if c["method"] == "get_attribute"),
            None,
        )
        assert get_attr_call is not None, "handler 应调用 get_attribute"
        assert get_attr_call["product_id"] == 301
        assert get_attr_call["attribute_code"] == "防水"

    @pytest.mark.asyncio
    async def test_compare_with_product_id_format_in_context(self) -> None:
        """product.compare 使用 product_id/product_name 候选格式也能成功。"""
        FakeProductSkill.reset()
        FakeProductSkill.add_product(101, name="Tab 11 平板电脑", price=1999.0)
        FakeProductSkill.add_product(102, name="Tab 11 Pro 平板电脑", price=2999.0)

        handler = ProductHandler(
            skill=FakeProductSkill,
            resolver=FakeResolver(),
        )
        ctx = make_context(
            product_candidates=[
                {"product_id": 101, "product_name": "Tab 11 平板电脑"},
                {"product_id": 102, "product_name": "Tab 11 Pro 平板电脑"},
            ],
        )
        decision = make_decision(
            "product.compare",
            text="第一款和第二款有什么区别",
        )

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.compare"
        assert result.pending_directive == PendingDirective.CLEAR
        assert "Tab 11 平板电脑" in result.reply
        assert "Tab 11 Pro 平板电脑" in result.reply
        assert "vs" in result.reply
        # product_id/product_name 格式被正确解析，candidates 被归一化
        assert result.context_update.get("compare_base_product_id") == "101"

    @pytest.mark.asyncio
    async def test_filter_search_calls_search_products(self) -> None:
        """product.filter_search 调用 search_products。"""
        FakeProductSkill.reset()
        FakeProductSkill.add_product(101, name="无线耳机")

        handler = ProductHandler(skill=FakeProductSkill, resolver=FakeResolver())
        ctx = make_context()
        decision = make_decision("product.filter_search", text="耳机")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "product.filter_search"
        search_call = next(
            (c for c in FakeProductSkill.call_log if c["method"] == "search_products"),
            None,
        )
        assert search_call is not None, "handler 应调用 search_products"


# ══════════════════════════════════════════════
# 11. ProductReplyBuilder 单元测试
# ══════════════════════════════════════════════


class TestProductReplyBuilder:
    """ProductReplyBuilder 回复模板单元测试。"""

    def test_category_list_with_children(self) -> None:
        """分类树含子分类。"""
        categories = [
            {"id": "1", "name": "电子产品", "parent_id": None, "children": [
                {"id": "2", "name": "手机", "parent_id": "1"},
                {"id": "3", "name": "电脑", "parent_id": "1"},
            ]},
            {"id": "4", "name": "家居用品", "parent_id": None, "children": []},
        ]
        reply = ProductReplyBuilder.category_list(categories)
        assert "商品分类如下" in reply
        assert "电子产品" in reply
        assert "手机" in reply
        assert "电脑" in reply

    def test_category_list_empty(self) -> None:
        """空分类列表。"""
        reply = ProductReplyBuilder.category_list([])
        assert "没有可用的商品分类" in reply

    def test_product_attributes_with_data(self) -> None:
        """结构化属性渲染。"""
        product = {
            "name": "无线蓝牙耳机",
            "feature_tags": ["热销", "新品"],
        }
        attrs = {"防水": "是", "降噪": "支持", "续航": "8小时"}
        reply = ProductReplyBuilder.product_attributes(product, attrs)
        assert "无线蓝牙耳机" in reply
        assert "防水" in reply
        assert "降噪" in reply
        assert "续航" in reply

    def test_product_attributes_no_attrs(self) -> None:
        """无属性数据时的回落文案。"""
        product = {"name": "测试商品"}
        reply = ProductReplyBuilder.product_attributes(product, None)
        assert "暂无结构化属性数据" in reply

    def test_product_list_empty(self) -> None:
        """空商品列表。"""
        reply = ProductReplyBuilder.product_list([])
        assert "没有找到" in reply

    def test_product_list_with_items(self) -> None:
        """商品列表渲染。"""
        products = [
            {"name": "商品A", "price": 100.0, "sku": "ABC001"},
            {"name": "商品B", "price": 200.0},
        ]
        reply = ProductReplyBuilder.product_list(products)
        assert "商品A" in reply
        assert "商品B" in reply
        assert "¥100.00" in reply
        assert "ABC001" in reply

    def test_product_detail_none(self) -> None:
        """product_detail 传入 None。"""
        reply = ProductReplyBuilder.product_detail(None)
        assert "没有找到" in reply

    def test_compare_result_less_than_two(self) -> None:
        """不足两个商品时对比返回提示。"""
        reply = ProductReplyBuilder.compare_result([{"name": "商品A"}])
        assert "至少两款" in reply

    def test_clarify_candidates_empty(self) -> None:
        """空候选追问。"""
        reply = ProductReplyBuilder.clarify_candidates([])
        assert "请提供更完整的商品名称" in reply

    def test_no_results_with_context(self) -> None:
        """带上下文的无结果提示。"""
        reply = ProductReplyBuilder.no_results("耳机")
        assert "耳机" in reply

    def test_no_results_empty(self) -> None:
        """无上下文的无结果提示。"""
        reply = ProductReplyBuilder.no_results()
        assert "没有找到" in reply
