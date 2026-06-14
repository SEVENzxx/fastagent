"""ProductReferenceResolver 单元测试。

覆盖场景：
  1. "第一款"从 product_candidates 解析
  2. "第3款"越界时返回 need_clarification
  3. "这个/这款/它"从 last_product_id 解析
  4. 没有上下文时"这个"不能硬猜
  5. 模糊产品名多候选时必须追问
  6. product_id 解析后必须重新校验 tenant_id/is_active
  7. 跨租户/下架产品不能解析成功
  8. "和第三款比"在上下文有候选时解析
  9. 裸数字（1/2）从候选列表解析
  10. 实体显式 product_id 解析
"""

from __future__ import annotations

from typing import Any

import pytest

from app.ai.components.product_reference_resolver import (
    ProductCandidate,
    ProductInfo,
    ProductLookupGateway,
    ProductReferenceResolver,
    ProductReferenceResult,
)
from app.ai.context.session_context import SessionContext


# ══════════════════════════════════════════════
# Fake 网关
# ══════════════════════════════════════════════


class FakeProductLookupGateway(ProductLookupGateway):
    """内存假网关，用于测试。

    所有产品预先注册。validate_product 检查 tenant_id + is_active。
    search_by_name 做精确和包含匹配。
    """

    def __init__(self) -> None:
        # product_id -> ProductInfo
        self._products: dict[int, ProductInfo] = {}

    def add_product(
        self,
        product_id: int,
        name: str,
        *,
        tenant_id: int = 1,
        is_active: bool = True,
    ) -> None:
        """注册一个测试产品。"""
        self._products[product_id] = ProductInfo(
            product_id=product_id,
            name=name,
            tenant_id=tenant_id,
            is_active=is_active,
        )

    async def validate_product(
        self,
        product_id: int,
        tenant_id: int,
    ) -> ProductInfo | None:
        info = self._products.get(product_id)
        if info is None:
            return None
        if info.tenant_id != tenant_id:
            return None
        if not info.is_active:
            return None
        return info

    async def search_by_name(
        self,
        name: str,
        tenant_id: int,
        *,
        limit: int = 10,
    ) -> list[ProductInfo]:
        results: list[ProductInfo] = []
        for p in self._products.values():
            if p.tenant_id != tenant_id or not p.is_active:
                continue
            if p.name == name or name in p.name or p.name in name:
                results.append(p)
                if len(results) >= limit:
                    break
        return results


# ══════════════════════════════════════════════
# 夹具
# ══════════════════════════════════════════════


def make_context(**overrides: Any) -> SessionContext:
    """构造 SessionContext，支持覆盖字段。"""
    defaults: dict[str, Any] = {
        "tenant_id": 1,
        "conversation_id": 1,
    }
    defaults.update(overrides)
    return SessionContext(**defaults)


@pytest.fixture
def gateway() -> FakeProductLookupGateway:
    g = FakeProductLookupGateway()
    # 一些默认测试产品
    g.add_product(101, "Tab 11 平板电脑")
    g.add_product(102, "Tab 11 Pro 平板电脑")
    g.add_product(103, "Galaxy Tab S9")
    g.add_product(201, "智能手表 Pro")
    g.add_product(202, "智能手表 Lite")
    g.add_product(301, "无线蓝牙耳机")
    return g


@pytest.fixture
def resolver(gateway: FakeProductLookupGateway) -> ProductReferenceResolver:
    return ProductReferenceResolver(gateway)


# ══════════════════════════════════════════════
# 1. 序号引用
# ══════════════════════════════════════════════


class TestOrdinalReference:
    """序号引用解析。"""

    @pytest.mark.asyncio
    async def test_first_from_candidates(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """第一款 → 从 product_candidates 解析。"""
        context = make_context(
            product_candidates=[
                {"id": 101, "name": "Tab 11 平板电脑"},
                {"id": 102, "name": "Tab 11 Pro 平板电脑"},
            ],
        )
        result = await resolver.resolve("第一款", {}, context, tenant_id=1)
        assert result.resolved is True
        assert result.product_id == 101
        assert result.product_name == "Tab 11 平板电脑"
        assert result.need_clarification is False

    @pytest.mark.asyncio
    async def test_second_from_candidates(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """第2个 → 从 product_candidates 解析第二个。"""
        context = make_context(
            product_candidates=[
                {"id": 101, "name": "Tab 11 平板电脑"},
                {"id": 102, "name": "Tab 11 Pro 平板电脑"},
                {"id": 103, "name": "Galaxy Tab S9"},
            ],
        )
        result = await resolver.resolve("第2个", {}, context, tenant_id=1)
        assert result.resolved is True
        assert result.product_id == 102

    @pytest.mark.asyncio
    async def test_ordinal_out_of_range(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """第3款越界 → need_clarification。"""
        context = make_context(
            product_candidates=[
                {"id": 101, "name": "Tab 11 平板电脑"},
                {"id": 102, "name": "Tab 11 Pro 平板电脑"},
            ],
        )
        result = await resolver.resolve("第3款", {}, context, tenant_id=1)
        assert result.resolved is False
        assert result.need_clarification is True
        assert "超出候选范围" in result.reason

    @pytest.mark.asyncio
    async def test_bare_number_from_candidates(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """裸数字 '1' 从候选列表解析。"""
        context = make_context(
            product_candidates=[
                {"id": 101, "name": "Tab 11 平板电脑"},
                {"id": 102, "name": "Tab 11 Pro 平板电脑"},
            ],
        )
        result = await resolver.resolve("1", {}, context, tenant_id=1)
        assert result.resolved is True
        assert result.product_id == 101

    @pytest.mark.asyncio
    async def test_bare_number_no_candidates_skips(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """裸数字但无候选时不应作为序号解析（可能为数量/价格）。"""
        context = make_context()
        result = await resolver.resolve("1", {}, context, tenant_id=1)
        # 无候选 → 进入名称搜索 → 找不到
        assert result.resolved is False
        assert result.need_clarification is True

    @pytest.mark.asyncio
    async def test_ordinal_from_active_product_ids(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """序号从 active_product_ids + active_product_names 解析。"""
        context = make_context(
            active_product_ids=["101", "102"],
            active_product_names=["Tab 11 平板电脑", "Tab 11 Pro 平板电脑"],
        )
        result = await resolver.resolve("第二款", {}, context, tenant_id=1)
        assert result.resolved is True
        assert result.product_id == 102

    @pytest.mark.asyncio
    async def test_no_candidates_ordinal_skips_to_name(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """无候选时第X款不作为序号解析→走名称搜索。"""
        context = make_context()
        result = await resolver.resolve("第三款", {}, context, tenant_id=1)
        # 没有 candidates，所以 _try_resolve_ordinal 返回 None（无candidates不处理）
        # 然后走名称搜索"第三款"
        assert result.resolved is False
        assert result.need_clarification is True


# ══════════════════════════════════════════════
# 2. 指代引用
# ══════════════════════════════════════════════


class TestDeixisReference:
    """指代引用解析。"""

    @pytest.mark.asyncio
    async def test_this_from_last_product_id(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """'这个'从 last_product_id 解析。"""
        context = make_context(last_product_id="101")
        result = await resolver.resolve("这个", {}, context, tenant_id=1)
        assert result.resolved is True
        assert result.product_id == 101
        assert result.product_name == "Tab 11 平板电脑"
        assert result.need_clarification is False

    @pytest.mark.asyncio
    async def test_this_product_from_last_product_id(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """'这款'从 last_product_id 解析。"""
        context = make_context(last_product_id="102")
        result = await resolver.resolve("这款", {}, context, tenant_id=1)
        assert result.resolved is True
        assert result.product_id == 102

    @pytest.mark.asyncio
    async def test_it_from_last_product_id(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """'它'从 last_product_id 解析。"""
        context = make_context(last_product_id="103")
        result = await resolver.resolve("它", {}, context, tenant_id=1)
        assert result.resolved is True
        assert result.product_id == 103

    @pytest.mark.asyncio
    async def test_no_context_cannot_guess(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """没有上下文时'这个'不能硬猜。"""
        context = make_context()  # no last_product_id
        result = await resolver.resolve("这个", {}, context, tenant_id=1)
        assert result.resolved is False
        assert result.need_clarification is True
        assert "没有最近浏览的商品" in result.reason

    @pytest.mark.asyncio
    async def test_that_previous_from_last_product_id(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """'刚才那个'从 last_product_id 解析。"""
        context = make_context(last_product_id="201")
        result = await resolver.resolve("刚才那个", {}, context, tenant_id=1)
        assert result.resolved is True
        assert result.product_id == 201
        assert result.product_name == "智能手表 Pro"


# ══════════════════════════════════════════════
# 3. 对比延续
# ══════════════════════════════════════════════


class TestCompareContinuation:
    """对比延续解析。"""

    @pytest.mark.asyncio
    async def test_compare_third_from_candidates(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """'和第三款比'从候选列表解析第三款。"""
        context = make_context(
            product_candidates=[
                {"id": 101, "name": "Tab 11 平板电脑"},
                {"id": 102, "name": "Tab 11 Pro 平板电脑"},
                {"id": 103, "name": "Galaxy Tab S9"},
            ],
        )
        result = await resolver.resolve("和第三款比", {}, context, tenant_id=1)
        assert result.resolved is True
        assert result.product_id == 103
        assert "对比延续" in result.reason

    @pytest.mark.asyncio
    async def test_compare_first_what_difference(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """'和第一款有什么区别'从候选列表解析。"""
        context = make_context(
            product_candidates=[
                {"id": 101, "name": "Tab 11 平板电脑"},
                {"id": 102, "name": "Tab 11 Pro 平板电脑"},
            ],
        )
        result = await resolver.resolve("和第一款有什么区别", {}, context, tenant_id=1)
        assert result.resolved is True
        assert result.product_id == 101

    @pytest.mark.asyncio
    async def test_compare_ordinal_out_of_range(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """对比序号越界 → need_clarification。"""
        context = make_context(
            product_candidates=[
                {"id": 101, "name": "Tab 11 平板电脑"},
            ],
        )
        result = await resolver.resolve("和第三款有什么区别", {}, context, tenant_id=1)
        assert result.resolved is False
        assert result.need_clarification is True
        assert "超出候选范围" in result.reason

    @pytest.mark.asyncio
    async def test_compare_no_candidates(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """对比但无候选 → need_clarification。"""
        context = make_context()
        result = await resolver.resolve("和第三款比", {}, context, tenant_id=1)
        assert result.resolved is False
        assert result.need_clarification is True
        assert "没有商品候选列表" in result.reason


# ══════════════════════════════════════════════
# 4. 产品名校验
# ══════════════════════════════════════════════


class TestNameSearch:
    """产品名搜索解析。"""

    @pytest.mark.asyncio
    async def test_exact_name_match(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """精确产品名匹配。"""
        context = make_context()
        result = await resolver.resolve("Tab 11 平板电脑", {}, context, tenant_id=1)
        assert result.resolved is True
        assert result.product_id == 101
        assert result.need_clarification is False

    @pytest.mark.asyncio
    async def test_fuzzy_name_match_multiple_candidates(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """模糊名称匹配到多个候选→追问。"""
        context = make_context()
        result = await resolver.resolve("Tab 11", {}, context, tenant_id=1)
        assert result.resolved is False
        assert result.need_clarification is True
        assert len(result.candidates) >= 2
        # 候选带序号
        assert result.candidates[0].index == 1
        assert result.candidates[1].index == 2
        assert result.candidates[0].product_name is not None

    @pytest.mark.asyncio
    async def test_no_match(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """无匹配产品→need_clarification。"""
        context = make_context()
        result = await resolver.resolve("不存在的产品XYZ", {}, context, tenant_id=1)
        assert result.resolved is False
        assert result.need_clarification is True
        assert "未找到匹配" in result.reason

    @pytest.mark.asyncio
    async def test_name_search_only_active(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """名称搜索只返回活跃产品。"""
        gateway.add_product(999, "已下架产品", tenant_id=1, is_active=False)
        context = make_context()
        result = await resolver.resolve("已下架产品", {}, context, tenant_id=1)
        assert result.resolved is False
        assert result.need_clarification is True


# ══════════════════════════════════════════════
# 5. product_id 校验
# ══════════════════════════════════════════════


class TestProductValidation:
    """product_id 校验测试。"""

    @pytest.mark.asyncio
    async def test_validate_tenant_id(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """跨租户产品不能解析。"""
        # 产品 101 属于租户 1，租户 2 不能访问
        context = make_context(
            product_candidates=[{"id": 101, "name": "Tab 11 平板电脑"}],
        )
        result = await resolver.resolve("第一款", {}, context, tenant_id=2)
        assert result.resolved is False
        assert result.need_clarification is True
        assert "已下架或不可见" in result.reason

    @pytest.mark.asyncio
    async def test_validate_is_active(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """下架产品不能解析。"""
        gateway.add_product(401, "老款手机", tenant_id=1, is_active=False)
        context = make_context(
            product_candidates=[{"id": 401, "name": "老款手机"}],
        )
        result = await resolver.resolve("第一款", {}, context, tenant_id=1)
        assert result.resolved is False
        assert result.need_clarification is True

    @pytest.mark.asyncio
    async def test_validate_by_entity_id(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """实体传入 product_id 后校验不通过→无法解析。"""
        context = make_context()
        result = await resolver.resolve(
            "查看这个产品", {"product_id": 999}, context, tenant_id=1,
        )
        assert result.resolved is False
        assert result.need_clarification is True
        assert "不存在或已下架" in result.reason

    @pytest.mark.asyncio
    async def test_validate_by_entity_id_ok(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """实体传入 product_id 校验通过→正常解析。"""
        context = make_context()
        result = await resolver.resolve(
            "查看这个产品", {"product_id": 101}, context, tenant_id=1,
        )
        assert result.resolved is True
        assert result.product_id == 101
        assert "按 product_id 解析" in result.reason


# ══════════════════════════════════════════════
# 6. 边界
# ══════════════════════════════════════════════


class TestEdgeCases:
    """边界情况。"""

    @pytest.mark.asyncio
    async def test_empty_text(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """空文本→need_clarification。"""
        context = make_context()
        result = await resolver.resolve("", {}, context, tenant_id=1)
        assert result.resolved is False
        assert result.need_clarification is True

    @pytest.mark.asyncio
    async def test_empty_entities_no_crash(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """空 entities 不崩溃。"""
        context = make_context()
        result = await resolver.resolve("你好", {}, context, tenant_id=1)
        assert result.resolved is False  # 显然不是产品引用

    @pytest.mark.asyncio
    async def test_deixis_but_product_gone(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """指代最近商品但已下架→need_clarification。"""
        gateway.add_product(501, "限时特价商品", tenant_id=1, is_active=False)
        context = make_context(last_product_id="501")
        result = await resolver.resolve("这个", {}, context, tenant_id=1)
        assert result.resolved is False
        assert result.need_clarification is True
        assert "已下架" in result.reason

    @pytest.mark.asyncio
    async def test_candidates_different_tenant(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """候选列表中的产品属于其他租户时不能跨租户解析。"""
        # 产品 101 属于租户 1
        context = make_context(
            product_candidates=[{"id": 101, "name": "Tab 11 平板电脑"}],
        )
        result = await resolver.resolve("第一款", {}, context, tenant_id=3)
        assert result.resolved is False
        assert result.need_clarification is True


# ══════════════════════════════════════════════
# 7. 指代前缀（Fix 1：真实追问句）
# ══════════════════════════════════════════════


class TestDeixisPrefix:
    """指代前缀解析：真实追问句中以指代词开头。"""

    @pytest.mark.asyncio
    async def test_this_earphone_waterproof(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """'这个耳机是否防水'→指代前缀解析到 last_product_id。"""
        context = make_context(last_product_id="101")
        result = await resolver.resolve("这个耳机是否防水", {}, context, tenant_id=1)
        assert result.resolved is True
        assert result.product_id == 101

    @pytest.mark.asyncio
    async def test_this_product_how(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """'这款怎么样'→指代前缀解析。"""
        context = make_context(last_product_id="102")
        result = await resolver.resolve("这款怎么样", {}, context, tenant_id=1)
        assert result.resolved is True
        assert result.product_id == 102

    @pytest.mark.asyncio
    async def test_it_suitable_for_kids(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """'它适合小孩吗'→指代前缀解析。"""
        context = make_context(last_product_id="103")
        result = await resolver.resolve("它适合小孩吗", {}, context, tenant_id=1)
        assert result.resolved is True
        assert result.product_id == 103

    @pytest.mark.asyncio
    async def test_previous_in_stock(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """'刚才那个还有货吗'→指代前缀解析。"""
        context = make_context(last_product_id="201")
        result = await resolver.resolve("刚才那个还有货吗", {}, context, tenant_id=1)
        assert result.resolved is True
        assert result.product_id == 201
        assert result.product_name == "智能手表 Pro"


# ══════════════════════════════════════════════
# 8. 候选格式兼容（Fix 2：product_id/product_name 键）
# ══════════════════════════════════════════════


class TestCandidateFormats:
    """product_candidates 多格式兼容。"""

    @pytest.mark.asyncio
    async def test_product_id_name_keys(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """product_candidates 使用 product_id/product_name 键。"""
        context = make_context(
            product_candidates=[
                {"product_id": 101, "product_name": "Tab 11 平板电脑"},
                {"product_id": 102, "product_name": "Tab 11 Pro 平板电脑"},
            ],
        )
        result = await resolver.resolve("第二款", {}, context, tenant_id=1)
        assert result.resolved is True
        assert result.product_id == 102

    @pytest.mark.asyncio
    async def test_product_candidate_model_dump_dicts(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """ProductCandidate.model_dump() 产生的字典格式可被解析。"""
        from app.ai.components.product_reference_resolver import ProductCandidate

        candidates = [
            ProductCandidate(index=1, product_id=101, product_name="Tab 11 平板电脑").model_dump(),
            ProductCandidate(index=2, product_id=102, product_name="Tab 11 Pro 平板电脑").model_dump(),
        ]
        context = make_context(product_candidates=candidates)
        result = await resolver.resolve("第一款", {}, context, tenant_id=1)
        assert result.resolved is True
        assert result.product_id == 101

    @pytest.mark.asyncio
    async def test_mixed_candidate_formats(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """混合格式的候选列表仍然正确解析。"""
        context = make_context(
            product_candidates=[
                {"id": 101, "name": "Tab 11 平板电脑"},
                {"product_id": 102, "product_name": "Tab 11 Pro 平板电脑"},
            ],
        )
        result = await resolver.resolve("第二款", {}, context, tenant_id=1)
        assert result.resolved is True
        assert result.product_id == 102

    @pytest.mark.asyncio
    async def test_candidate_product_id_out_of_range(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """product_id/product_name 格式越界→need_clarification。"""
        context = make_context(
            product_candidates=[
                {"product_id": 101, "product_name": "Tab 11"},
            ],
        )
        result = await resolver.resolve("第3款", {}, context, tenant_id=1)
        assert result.resolved is False
        assert result.need_clarification is True
        assert "超出候选范围" in result.reason


# ══════════════════════════════════════════════
# 9. last_focus_product_id / compare_base_product_id（Fix 3）
# ══════════════════════════════════════════════


class TestFocusAndCompareFields:
    """last_focus_product_id 和 compare_base_product_id 字段。"""

    @pytest.mark.asyncio
    async def test_last_focus_product_id_for_deixis(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """last_focus_product_id 用于指代解析。"""
        context = make_context(last_focus_product_id="101")
        result = await resolver.resolve("这个", {}, context, tenant_id=1)
        assert result.resolved is True
        assert result.product_id == 101

    @pytest.mark.asyncio
    async def test_last_focus_fallback_to_last_product(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """last_focus_product_id 为空时 fallback 到 last_product_id。"""
        context = make_context(last_product_id="102")
        result = await resolver.resolve("这款", {}, context, tenant_id=1)
        assert result.resolved is True
        assert result.product_id == 102

    @pytest.mark.asyncio
    async def test_compare_base_product_id_field_exists(
        self,
        resolver: ProductReferenceResolver,
        gateway: FakeProductLookupGateway,
    ) -> None:
        """compare_base_product_id 字段存在且可写（Handler 后续使用）。"""
        context = make_context(compare_base_product_id="101")
        assert context.compare_base_product_id == "101"
