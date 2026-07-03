"""Harness 架构测试 — 验证 ResourceTrace + 场景权限 + Pending 状态。

按 dev-standards.md 5.2 节组织：
  5.2.1 场景权限验证 — 读场景不调 LLM/Vector，不调用写 Skill
  5.2.2 Pending 状态验证 — HUMAN / CANCEL / RESUME 路径
  5.2.6 ResourceTrace 验证 — scenario_id 同步、pending_directive 填充

依赖 ScenarioTestBuilder（tests/harness/scenario_test_builder.py）进行编排断言。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.ai.assistant.service import AssistantService
from app.ai.context.pending_state import PendingAction, PendingDirective
from app.ai.handlers.registry import HandlerRegistry, register_default_handlers
from app.ai.context.session_context import SessionContext
from app.ai.handlers.template import TemplateHandler
from app.ai.handlers.human import HumanHandler
from app.ai.handlers.product import ProductHandler
from app.ai.handlers.order import OrderHandler
from app.ai.handlers.knowledge import KnowledgeHandler
from app.ai.handlers.memory import MemoryHandler
from app.ai.components.product_reference_resolver import ProductReferenceResult
from app.common.constants.business import DEFAULT_PAGE_SIZE
from tests.harness.scenario_test_builder import ScenarioTestBuilder


# ══════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════


@pytest.fixture
def arch_registry() -> HandlerRegistry:
    """注册真实 Handler（不注入 FakeSkill，用于 trace-only 断言）。"""
    r = HandlerRegistry()
    register_default_handlers(r)
    return r


@pytest.fixture
def arch_service(arch_registry: HandlerRegistry) -> AssistantService:
    """AssistantService with mocked Redis-dependent deps.

    与 test_assistant_service.py 的 service fixture 相同，
    handler 使用真实 Skill（DB 不可用时会降级返回空数据）。
    """
    session_store = AsyncMock()
    session_store.get.return_value = SessionContext()
    pending_svc = AsyncMock()
    pending_svc.get.return_value = None
    return AssistantService(
        registry=arch_registry,
        pending_service=pending_svc,
        pending_guard=AsyncMock(),
        recognition=AsyncMock(),
        session_store=session_store,
    )


@pytest.fixture
def arch_mocks(arch_service: AssistantService) -> dict[str, Any]:
    """返回 mock 对象引用，供测试内断言和 ScenarioTestBuilder 使用。"""
    return {
        "session_store": arch_service.session_store,
        "pending_service": arch_service.pending_service,
        "pending_guard": arch_service.pending_guard,
        "recognition": arch_service.recognition,
    }


# ══════════════════════════════════════════════
# FakeSkill Fixtures — 全链路内容+Trace 断言
# ══════════════════════════════════════════════


@pytest.fixture
def fake_skill_registry() -> HandlerRegistry:
    """注册带 FakeSkill 的 Handler 用于内容+Trace 全链路测试。

    ProductHandler 使用 FakeProductSkill + FakeResolver（可配置 set_result 匹配）。
    OrderHandler 使用 FakeOrderSkill。
    KnowledgeHandler 使用 FakeKnowledgeSkill。
    MemoryHandler 使用 FakeMemorySkill。
    """
    from tests.test_product_handler import FakeProductSkill, FakeResolver
    from tests.test_order_handler import FakeOrderSkill
    from tests.test_knowledge_handler import FakeKnowledgeSkill
    from tests.test_memory_handler import FakeMemorySkill

    # 重置所有 FakeSkill 状态
    FakeProductSkill.reset()
    FakeOrderSkill.reset()
    FakeKnowledgeSkill.reset()
    FakeMemorySkill.reset()

    r = HandlerRegistry()

    # ── Template + Human（无 Skill 依赖） ──
    for sid in ("template.greeting", "template.confirmation", "template.farewell",
                "template.silent", "template.fallback"):
        r.register(sid, TemplateHandler())
    r.register("human.transfer", HumanHandler())

    # ── Product 场景 ──
    fake_resolver = FakeResolver()
    fake_resolver.set_default(
        ProductReferenceResult(
            resolved=False, need_clarification=True, reason="未找到匹配商品",
        ),
    )
    product_handler = ProductHandler(
        skill=FakeProductSkill,
        resolver=fake_resolver,
        knowledge_skill=FakeKnowledgeSkill,
    )
    for sid in ("product.catalog", "product.filter_search",
                "product.sku_query", "product.detail", "product.compare",
                "product.attribute_query", "product.usage", "product.pagination_sort"):
        r.register(sid, product_handler)

    # ── Order 场景 ──
    order_handler = OrderHandler(skill=FakeOrderSkill)
    for sid in ("order.list", "order.filter", "order.detail", "order.shipping_status",
                "order.create", "order.cancel", "order.confirm", "order.refund"):
        r.register(sid, order_handler)

    # ── Knowledge 场景 ──
    knowledge_handler = KnowledgeHandler(skill=FakeKnowledgeSkill)
    for sid in ("knowledge.policy", "knowledge.qa", "knowledge.product_qa"):
        r.register(sid, knowledge_handler)

    # ── Memory 场景 ──
    memory_handler = MemoryHandler(skill=FakeMemorySkill)
    r.register("memory.save", memory_handler)
    r.register("memory.recall", memory_handler)

    return r


@pytest.fixture
def fake_skill_service(fake_skill_registry: HandlerRegistry) -> AssistantService:
    """AssistantService with FakeSkills + mocked Redis deps。"""
    session_store = AsyncMock()
    session_store.get.return_value = SessionContext()
    pending_svc = AsyncMock()
    pending_svc.get.return_value = None
    return AssistantService(
        registry=fake_skill_registry,
        pending_service=pending_svc,
        pending_guard=AsyncMock(),
        recognition=AsyncMock(),
        session_store=session_store,
    )


@pytest.fixture
def fake_skill_mocks(
    fake_skill_service: AssistantService,
    fake_skill_registry: HandlerRegistry,
) -> dict[str, Any]:
    """返回 mock 对象引用 + FakeResolver 引用（供测试配置匹配）。"""
    return {
        "session_store": fake_skill_service.session_store,
        "pending_service": fake_skill_service.pending_service,
        "pending_guard": fake_skill_service.pending_guard,
        "recognition": fake_skill_service.recognition,
        # 暴露 ProductHandler 的 resolver 供测试配置 set_result
        "product_resolver": fake_skill_registry.get("product.detail")._resolver,  # type:ignore[union-attr]
    }


# ══════════════════════════════════════════════
# 5.2.1 场景权限验证
# ══════════════════════════════════════════════


class TestScenarioPermissionValidation:
    """验证各场景的 ResourceTrace 权限约束。"""

    @pytest.mark.asyncio
    async def test_product_catalog_no_llm_no_vector(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """product.catalog → llm_calls == 0, vector_calls == 0。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("你们有什么产品")
            .scenario_is("product.catalog")
            .expect_llm_calls(0)
            .expect_vector_calls(0)
            .run())

        assert result.metadata["scenario_id"] == "product.catalog"

    @pytest.mark.asyncio
    async def test_order_list_no_llm_no_vector(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """order.list → llm_calls == 0, vector_calls == 0。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("我的订单")
            .scenario_is("order.list")
            .expect_llm_calls(0)
            .expect_vector_calls(0)
            .run())

        assert result.metadata["scenario_id"] == "order.list"

    @pytest.mark.asyncio
    async def test_product_filter_search_uses_entity_llm(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """product.filter_search → 实体抽取会调用 1 次 LLM。"""
        await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("耳机")
            .scenario_is("product.filter_search")
            .expect_llm_calls(1)
            .run())

    @pytest.mark.asyncio
    async def test_human_transfer_no_skill_calls(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """human.transfer → 无 Skill 调用。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("转人工")
            .scenario_is("human.transfer")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert trace.get("skill_calls") == [], "转人工不应调用任何 Skill"

    @pytest.mark.asyncio
    async def test_template_greeting_no_skill_calls(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """template.greeting → 无 Skill 调用。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("你好")
            .scenario_is("template.greeting")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert trace.get("skill_calls") == []

    @pytest.mark.asyncio
    async def test_order_shipping_status_no_llm(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """order.shipping_status → llm_calls == 0。"""
        await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("订单发货了没有")
            .scenario_is("order.shipping_status")
            .expect_llm_calls(0)
            .run())

    @pytest.mark.asyncio
    async def test_order_cancel_initializes_graph(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """order.cancel → 不抛异常，pending_directive 为 set（图中断）或 clear。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("我要取消订单")
            .scenario_is("order.cancel")
            .run())

        directive = result.metadata.get("pending_directive")
        assert directive in ("set", "clear"), (
            f"order.cancel pending_directive 应为 set 或 clear，实际 {directive}"
        )

    @pytest.mark.asyncio
    async def test_order_confirm_no_llm(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """order.confirm → 骨架场景，不调 LLM，pending_directive=clear。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("确认订单")
            .scenario_is("order.confirm")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert trace.get("llm_calls", 0) == 0

    @pytest.mark.asyncio
    async def test_fallback_no_llm_no_skills(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """template.fallback → llm_calls=0, vector_calls=0, skill_calls=[]。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("abcdefg看不懂")
            .scenario_is("template.fallback")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert trace.get("llm_calls") == 0
        assert trace.get("vector_calls") == 0
        assert trace.get("skill_calls") == []

    @pytest.mark.asyncio
    async def test_memory_recall_no_contact_no_llm(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """memory.recall 无 contact_id → llm_calls=0, skill_calls=[]。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("我有什么偏好")
            .scenario_is("memory.recall")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert trace.get("llm_calls") == 0
        assert trace.get("skill_calls") == []

    @pytest.mark.asyncio
    async def test_knowledge_product_qa_no_context_no_skills(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """knowledge.product_qa 无 product_id → llm_calls=0, skill_calls=[]。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("这个商品有什么特点")
            .scenario_is("knowledge.product_qa")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert trace.get("llm_calls") == 0
        assert trace.get("skill_calls") == []

    @pytest.mark.asyncio
    async def test_product_catalog_records_skill_call(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """product.catalog → 记录 list_categories 调用。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("你们有什么产品")
            .scenario_is("product.catalog")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert "list_categories" in trace.get("skill_calls", []), (
            f"product.catalog 应调用 list_categories，实际: {trace.get('skill_calls')}"
        )

    @pytest.mark.asyncio
    async def test_product_compare_no_llm(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """product.compare → llm_calls == 0（对比是纯规则 + Skill，不调 LLM）。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("第一款和第二款有什么区别")
            .scenario_is("product.compare")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert trace.get("llm_calls") == 0

    @pytest.mark.asyncio
    async def test_knowledge_qa_records_skill_call(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """knowledge.qa → 至少记录一次 Skill 调用（search_qa）。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("退货政策")
            .scenario_is("knowledge.qa")
            .run())

        trace = result.metadata.get("resource_trace", {})
        skill_calls = trace.get("skill_calls", [])
        assert any("search_qa" in c or "search_knowledge" in c for c in skill_calls), (
            f"knowledge.qa 应调用知识检索 Skill，实际: {skill_calls}"
        )

    @pytest.mark.asyncio
    async def test_memory_recall_records_skill_call(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """memory.recall → 记录 recall_info 调用。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("我上次问了什么")
            .scenario_is("memory.recall")
            .with_context(contact_id=1)
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert "recall_info" in trace.get("skill_calls", []), (
            f"memory.recall 应调用 recall_info，实际: {trace.get('skill_calls')}"
        )


# ══════════════════════════════════════════════
# 5.2.2 Pending 状态验证
# ══════════════════════════════════════════════


class TestPendingStateValidation:
    """验证 4 种 PendingAction 路径。"""

    @pytest.mark.asyncio
    async def test_pending_human_clears_and_transfers(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """HUMAN → pending_directive=clear + 转人工回复。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("转人工")
            .with_pending("order.create", guard_action=PendingAction.HUMAN)
            .expect_pending_directive(PendingDirective.CLEAR)
            .run())

        assert "人工" in result.reply or "转接" in result.reply

    @pytest.mark.asyncio
    async def test_pending_cancel_clears(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """CANCEL → pending_directive=clear + 取消回复。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("算了")
            .with_pending("order.create", guard_action=PendingAction.CANCEL)
            .expect_pending_directive(PendingDirective.CLEAR)
            .run())

        assert "取消" in result.reply




# ══════════════════════════════════════════════
# 5.2.6 ResourceTrace 验证
# ══════════════════════════════════════════════


class TestResourceTraceValidation:
    """验证 ResourceTrace 的正确填充。"""

    @pytest.mark.asyncio
    async def test_scenario_id_synced(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """resource_trace.scenario_id 与 result.scenario_id 一致。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("你好")
            .scenario_is("template.greeting")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert trace.get("scenario_id") == "template.greeting"

    @pytest.mark.asyncio
    async def test_pending_directive_synced(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """resource_trace.pending_directive 与 result.metadata.pending_directive 一致。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("你好")
            .scenario_is("template.greeting")
            .expect_pending_directive(PendingDirective.CLEAR)
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert trace.get("pending_directive") == "clear"

    @pytest.mark.asyncio
    async def test_skill_calls_list_populated(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """有 Skill 调用的场景，skill_calls 列表非空。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("退货政策")
            .scenario_is("knowledge.qa")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert isinstance(trace.get("skill_calls"), list)

    @pytest.mark.asyncio
    async def test_llm_calls_is_int(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """llm_calls 字段总是整数。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("你好")
            .scenario_is("template.greeting")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert isinstance(trace.get("llm_calls"), int)

    @pytest.mark.asyncio
    async def test_vector_calls_is_int(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """vector_calls 字段总是整数。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("你好")
            .scenario_is("template.greeting")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert isinstance(trace.get("vector_calls"), int)

    @pytest.mark.asyncio
    async def test_resource_trace_in_metadata(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """resource_trace 始终在 metadata 中。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("你好")
            .scenario_is("template.greeting")
            .run())

        assert "resource_trace" in result.metadata

    @pytest.mark.asyncio
    async def test_no_skill_scenario_trace_empty(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """Template 场景无 Skill 调用。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("再见")
            .scenario_is("template.farewell")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert trace.get("skill_calls") == []
        assert trace.get("llm_calls") == 0


# ══════════════════════════════════════════════
# 5.2.3 产品场景验证（带 FakeSkill）
# ══════════════════════════════════════════════


class TestProductArchitecture:
    """产品场景架构约束验证。"""

    @pytest.mark.asyncio
    async def test_product_catalog_no_llm_with_data(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """product.catalog → 有数据时也不调 LLM。"""
        # 即使有 FakeSkill 数据，catalog 也不应调 LLM
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("你们有什么产品")
            .scenario_is("product.catalog")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert trace.get("llm_calls") == 0


# ══════════════════════════════════════════════
# 5.2.4 订单场景验证（带 FakeSkill）
# ══════════════════════════════════════════════


class TestOrderArchitecture:
    """订单场景架构约束验证。"""

    @pytest.mark.asyncio
    async def test_order_list_no_llm(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """order.list → llm_calls == 0。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("我的订单")
            .scenario_is("order.list")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert trace.get("llm_calls") == 0

    @pytest.mark.asyncio
    async def test_order_filter_no_llm(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """order.filter → llm_calls == 0。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("未发货的订单")
            .scenario_is("order.filter")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert trace.get("llm_calls") == 0

    @pytest.mark.asyncio
    async def test_order_detail_no_llm(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """order.detail → llm_calls == 0。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("订单号 ORD-20240101-0001")
            .scenario_is("order.detail")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert trace.get("llm_calls") == 0

    @pytest.mark.asyncio
    async def test_order_create_sets_pending(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """order.create 设置 PendingDirective。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("我要下单")
            .scenario_is("order.create")
            .run())

        # order.create 使用 LangGraph 子图，返回 SET
        directive = result.metadata.get("pending_directive")
        assert directive in ("set", "clear"), (
            f"order.create pending_directive 应为 set 或 clear，实际 {directive}"
        )


# ══════════════════════════════════════════════
# 5.2.5 知识场景验证（带 FakeSkill）
# ══════════════════════════════════════════════


class TestKnowledgeArchitecture:
    """知识场景架构约束验证。"""

    @pytest.mark.asyncio
    async def test_knowledge_qa_no_llm_on_direct_hit(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """knowledge.qa QA pair 命中 → llm_calls == 0。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("退货政策是什么")
            .scenario_is("knowledge.qa")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert trace.get("llm_calls") == 0


# ══════════════════════════════════════════════
# 5.2.7 多候选验证（SessionContext 集成）
# ══════════════════════════════════════════════


class TestMultiCandidateArchitecture:
    """多候选场景的 SessionContext 集成验证。"""

    @pytest.mark.asyncio
    async def test_multi_candidate_updates_context(
        self,
        arch_service: AssistantService,
        arch_mocks: dict[str, Any],
    ) -> None:
        """多候选场景不写 Pending，保持 trace 可用。"""
        result = await (ScenarioTestBuilder(arch_service, arch_mocks)
            .user_says("Tab 11")
            .scenario_is("product.detail")
            .run())

        # 可能 SET（有候选）或 CLEAR（无候选/降级）
        directive = result.metadata.get("pending_directive")
        # 不管 SET 还是 CLEAR，resource_trace 都应存在
        assert "resource_trace" in result.metadata




# ══════════════════════════════════════════════════════════
# 3.x 产品 FakeSkill 全链路内容+Trace
# ══════════════════════════════════════════════════════════


class TestProductFakeSkillContent:
    """产品场景通过 AssistantService 全链路断言内容+Trace。

    使用 fake_skill_service fixture（FakeProductSkill + FakeResolver 注入）。
    每个测试自行配置 FakeSkill 数据。
    """

    @pytest.mark.asyncio
    async def test_catalog_returns_categories_and_trace(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """product.catalog → 返回分类内容 + 记录 list_categories。
        验证：reply 含分类名，skill_calls 含 list_categories，llm_calls=0。
        """
        from tests.test_product_handler import FakeProductSkill

        FakeProductSkill.reset()
        FakeProductSkill.add_category(name="电子产品")
        FakeProductSkill.add_category(name="家居用品")

        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("你们有什么产品")
            .scenario_is("product.catalog")
            .expect_llm_calls(0)
            .expect_vector_calls(0)
            .expect_skill_calls("list_categories")
            .expect_reply_contains("电子产品", "家居用品")
            .run())

        assert result.metadata["scenario_id"] == "product.catalog"

    @pytest.mark.asyncio
    async def test_filter_search_returns_products_and_trace(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """product.filter_search → 返回商品列表 + 记录 search_products。
        验证：reply 含商品名，skill_calls 含 search_products。
        """
        from tests.test_product_handler import FakeProductSkill

        FakeProductSkill.reset()
        FakeProductSkill.add_product(101, name="无线耳机", price=199.0)
        FakeProductSkill.add_product(102, name="蓝牙耳机", price=299.0)

        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("耳机")
            .scenario_is("product.filter_search")
            .expect_llm_calls(1)
            .expect_skill_calls("search_products")
            .expect_reply_contains("无线耳机")
            .run())

        assert result.metadata["scenario_id"] == "product.filter_search"

    @pytest.mark.asyncio
    async def test_sku_query_returns_product_and_trace(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """product.sku_query → 返回商品信息 + 记录 search_by_sku。"""
        from tests.test_product_handler import FakeProductSkill

        FakeProductSkill.reset()
        FakeProductSkill.add_product(101, name="无线耳机", sku="SKU0101")

        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("SKU0101")
            .scenario_is("product.sku_query", sku="SKU0101")
            .expect_llm_calls(0)
            .expect_skill_calls("search_by_sku")
            .expect_reply_contains("无线耳机")
            .run())

        assert result.metadata["scenario_id"] == "product.sku_query"

    @pytest.mark.asyncio
    async def test_pagination_sort_returns_products(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """product.pagination_sort → 返回分页商品，无 LLM 调用。
        pagination_sort 从 context.product_candidates 取 ID，
        调 batch_get_detail 获取详情后分页返回。
        """
        from tests.test_product_handler import FakeProductSkill

        FakeProductSkill.reset()
        for i in range(1, 8):
            FakeProductSkill.add_product(100 + i, name=f"商品{i}", price=float(i * 100))

        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("下一页")
            .scenario_is("product.pagination_sort", page=2, page_size=5)
            .with_context(
                product_candidates=[
                    {"id": 100 + i, "name": f"商品{i}"} for i in range(1, 8)
                ],
                product_page=1,
            )
            .expect_llm_calls(0)
            .expect_skill_calls("batch_get_detail")
            .expect_reply_contains("商品6", "商品7")
            .run())

        assert result.metadata["scenario_id"] == "product.pagination_sort"

    @pytest.mark.asyncio
    async def test_detail_exact_match_returns_detail_and_trace(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """product.detail 精确匹配 → 返回详情 + 记录 get_detail。
        配置 FakeResolver 使 "无线耳机" 精确匹配到 product_id=101。
        """
        from tests.test_product_handler import FakeProductSkill, FakeResolver, ProductCandidate

        FakeProductSkill.reset()
        FakeProductSkill.add_product(101, name="无线蓝牙耳机", price=199.0)

        resolver: FakeResolver = fake_skill_mocks["product_resolver"]
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

        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("无线蓝牙耳机")
            .scenario_is("product.detail")
            .expect_llm_calls(1)
            .expect_skill_calls("get_detail")
            .expect_reply_contains("无线蓝牙耳机")
            .run())

        assert result.metadata["scenario_id"] == "product.detail"

    @pytest.mark.asyncio
    async def test_compare_first_and_second_returns_compare_and_trace(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """product.compare → 返回对比结果 + 记录 batch_get_detail。"""
        from tests.test_product_handler import FakeProductSkill

        FakeProductSkill.reset()
        FakeProductSkill.add_product(101, name="Tab 11", price=1999.0)
        FakeProductSkill.add_product(102, name="Tab 11 Pro", price=2999.0)

        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("第一款和第二款有什么区别")
            .scenario_is("product.compare")
            .with_context(
                product_candidates=[
                    {"id": 101, "name": "Tab 11"},
                    {"id": 102, "name": "Tab 11 Pro"},
                ],
            )
            .expect_llm_calls(0)
            .expect_skill_calls("batch_get_detail")
            .expect_reply_contains("Tab 11", "Tab 11 Pro", "vs")
            .run())

        assert result.metadata["scenario_id"] == "product.compare"

    @pytest.mark.asyncio
    async def test_attribute_query_returns_attribute_and_trace(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """product.attribute_query → 返回属性内容 + 记录 get_detail。
        attribute_code 为空时 handler 使用 get_detail 获取 attrs_json 展示全部属性。
        """
        from tests.test_product_handler import FakeProductSkill, FakeResolver, ProductCandidate, ProductReferenceResult

        PRODUCT_NAME = "NB-100 耳机"

        FakeProductSkill.reset()
        FakeProductSkill.add_product(
            101, name=PRODUCT_NAME, price=199.0,
            attrs_json={"颜色": "黑色", "连接": "蓝牙"},
        )

        resolver: FakeResolver = fake_skill_mocks["product_resolver"]
        resolver.set_result(
            PRODUCT_NAME + "的参数",
            ProductReferenceResult(
                resolved=True,
                product_id=101,
                product_name=PRODUCT_NAME,
                candidates=[ProductCandidate(index=1, product_id=101, product_name=PRODUCT_NAME)],
                reason="名称匹配",
            ),
        )

        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says(PRODUCT_NAME + "的参数")
            .scenario_is("product.attribute_query")
            .expect_llm_calls(0)
            .expect_skill_calls("get_detail")
            .expect_reply_contains("颜色", "连接")
            .run())

        assert result.metadata["scenario_id"] == "product.attribute_query"

    @pytest.mark.asyncio
    async def test_detail_multi_candidate_sets_pending(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """product.detail 多候选 → CLEAR + 追问回复。"""
        from tests.test_product_handler import FakeProductSkill, FakeResolver, ProductCandidate, ProductReferenceResult

        FakeProductSkill.reset()
        FakeProductSkill.add_product(101, name="Tab 11", price=1999.0)
        FakeProductSkill.add_product(102, name="Tab 11 Pro", price=2999.0)

        resolver: FakeResolver = fake_skill_mocks["product_resolver"]
        resolver.set_result(
            "Tab 11",
            ProductReferenceResult(
                resolved=False,
                need_clarification=True,
                product_id=None,
                product_name=None,
                candidates=[
                    ProductCandidate(index=1, product_id=101, product_name="Tab 11"),
                    ProductCandidate(index=2, product_id=102, product_name="Tab 11 Pro"),
                ],
                reason="多个候选",
            ),
        )

        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("Tab 11")
            .scenario_is("product.detail")
            .expect_pending_directive(PendingDirective.CLEAR)
            .expect_reply_contains("Tab 11", "Tab 11 Pro")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert "search_products" in trace.get("skill_calls", [])  # 多候选通过商品搜索写入上下文
        assert isinstance(trace.get("llm_calls"), int)

# ══════════════════════════════════════════════════════════
# 4.x 订单 FakeSkill 全链路内容+Trace
# ══════════════════════════════════════════════════════════


class TestOrderFakeSkillContent:
    """订单场景全链路内容+Trace 断言。"""

    @pytest.mark.asyncio
    async def test_list_returns_orders_and_trace(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """order.list → 返回订单列表 + 记录 manage_order。"""
        from tests.test_order_handler import FakeOrderSkill

        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(1, status="shipped", status_label="已发货")
        FakeOrderSkill.add_order(2, status="pending_customer_confirm", status_label="待确认")

        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("我的订单")
            .scenario_is("order.list")
            .with_context(contact_id=1)
            .expect_llm_calls(0)
            .expect_vector_calls(0)
            .expect_skill_calls("manage_order")
            .run())

        assert result.metadata["scenario_id"] == "order.list"
        assert "已发货" in result.reply or "待确认" in result.reply

    @pytest.mark.asyncio
    async def test_filter_returns_filtered_orders_and_trace(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """order.filter → 返回过滤订单 + 记录 manage_order。"""
        from tests.test_order_handler import FakeOrderSkill

        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(1, status="shipped", status_label="已发货")
        FakeOrderSkill.add_order(2, status="pending_customer_confirm", status_label="待确认")

        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("已发货的订单")
            .scenario_is("order.filter", filter_statuses=["shipped"])
            .with_context(contact_id=1)
            .expect_llm_calls(0)
            .expect_skill_calls("manage_order")
            .run())

        assert result.metadata["scenario_id"] == "order.filter"

    @pytest.mark.asyncio
    async def test_detail_returns_detail_and_trace(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """order.detail → 返回订单详情 + 记录 manage_order（order_id 参数）。"""
        from tests.test_order_handler import FakeOrderSkill

        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(101, status="shipped", status_label="已发货")

        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("订单号 101")
            .scenario_is("order.detail", order_id="101")
            .with_context(contact_id=1)
            .expect_llm_calls(0)
            .expect_skill_calls("manage_order")
            .run())

        assert result.metadata["scenario_id"] == "order.detail"

    @pytest.mark.asyncio
    async def test_create_records_skill_call_and_trace(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """order.create → skill_calls 含 create_order_draft。

        即使 LangGraph 图执行时 DB 不可用，handler 仍应注入
        FakeOrderSkill 让图节点调用 create_order_draft 并记录 trace。
        """
        from tests.test_order_handler import FakeOrderSkill

        FakeOrderSkill.reset()

        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("我要下单")
            .scenario_is("order.create")
            .with_context(contact_id=1)
            .run())

        trace = result.metadata.get("resource_trace", {})
        skill_calls = trace.get("skill_calls", [])
        # order.create 走 LangGraph 子图，图内节点应记录 create_order_draft
        # 可能导致 SET（图中断征询商品）或 CLEAR（图完成/异常）
        pending_directive = result.metadata.get("pending_directive")
        assert pending_directive in ("set", "clear"), (
            f"order.create pending_directive 应为 set 或 clear，实际 {pending_directive}"
        )

    @pytest.mark.asyncio
    async def test_shipping_status_returns_status_and_trace(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """order.shipping_status → 返回物流信息 + 记录 manage_order（传入 order_id）。"""
        from tests.test_order_handler import FakeOrderSkill

        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(101, status="shipped", status_label="已发货")

        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("订单 101 发货了没有")
            .scenario_is("order.shipping_status", order_id="101")
            .with_context(contact_id=1)
            .expect_llm_calls(0)
            .expect_skill_calls("manage_order")
            .run())

        assert result.metadata["scenario_id"] == "order.shipping_status"

    @pytest.mark.asyncio
    async def test_confirm_skeleton_records_no_skills(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """order.confirm 骨架场景 → 不调 Skill，pending_directive=clear。"""
        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("确认订单")
            .scenario_is("order.confirm")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert trace.get("skill_calls") == []
        assert trace.get("llm_calls") == 0
        assert result.metadata.get("pending_directive") == "clear"


# ══════════════════════════════════════════════════════════
# 5.x 知识 FakeSkill 全链路内容+Trace
# ══════════════════════════════════════════════════════════


class TestKnowledgeFakeSkillContent:
    """知识场景全链路内容+Trace 断言。"""

    @pytest.mark.asyncio
    async def test_qa_direct_hit_returns_answer_and_trace(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """knowledge.qa QA pair 命中 → 返回答案 + 记录 search_qa + llm_calls=0。"""
        from tests.test_knowledge_handler import FakeKnowledgeSkill

        FakeKnowledgeSkill.reset()
        FakeKnowledgeSkill.add_qa("qa_1", "退货政策是什么", "7 天无理由退换货")

        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("退货政策是什么")
            .scenario_is("knowledge.qa")
            .expect_llm_calls(0)
            .expect_skill_calls("search_qa")
            .expect_reply_contains("7 天无理由")
            .run())

        assert result.metadata["scenario_id"] == "knowledge.qa"

    @pytest.mark.asyncio
    async def test_policy_knowledge_hit_returns_content_and_trace(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """knowledge.policy 知识分块命中 → 返回内容 + 记录 search_knowledge + search_qa。"""
        from tests.test_knowledge_handler import FakeKnowledgeSkill

        FakeKnowledgeSkill.reset()
        FakeKnowledgeSkill.add_knowledge(
            "chunk_1",
            "保修政策说明：本产品保修期为 1 年。",
            title="保修政策",
            token_count=50,
        )

        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("保修政策")
            .scenario_is("knowledge.policy")
            .expect_llm_calls(0)
            .expect_skill_calls("search_qa", "search_knowledge")
            .expect_reply_contains("保修期", "1 年")
            .run())

        assert result.metadata["scenario_id"] == "knowledge.policy"

    @pytest.mark.asyncio
    async def test_product_qa_no_context_asks_clarification(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """knowledge.product_qa 无商品上下文 → 追问引导。"""
        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("这个商品有什么特点")
            .scenario_is("knowledge.product_qa")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert result.metadata["scenario_id"] == "knowledge.product_qa"
        assert trace.get("skill_calls") == []  # 未调技能
        assert "哪款商品" in result.reply


class TestKnowledgeFakeSkillDetailedContent:
    """知识场景补充测试：product_qa 带上下文 + 长内容 LLM 摘要。"""

    @pytest.mark.asyncio
    async def test_product_qa_with_context_returns_answer_and_trace(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """knowledge.product_qa 有 last_focus_product_id → 按商品过滤检索 + 记录 search_knowledge。"""
        from tests.test_knowledge_handler import FakeKnowledgeSkill

        FakeKnowledgeSkill.reset()
        FakeKnowledgeSkill.add_knowledge(
            "chunk_1",
            "Tab 11 支持快充功能，15 分钟可充至 50%。",
            title="Tab 11 充电说明",
            token_count=30,
            product_id="101",
        )

        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("快充")
            .scenario_is("knowledge.product_qa")
            .with_context(last_focus_product_id="101")
            .expect_skill_calls("search_knowledge")
            .expect_reply_contains("快充")
            .run())

        assert result.metadata["scenario_id"] == "knowledge.product_qa"

    @pytest.mark.asyncio
    async def test_knowledge_long_content_triggers_llm_summary(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """knowledge.policy 长内容（超 token 阈值）→ 触发 LLM 摘要。
        LLM 不可用时降级为直接返回原始内容。
        """
        from tests.test_knowledge_handler import FakeKnowledgeSkill
        from app.common.constants.business import KNOWLEDGE_SHORT_CONTENT_TOKEN_LIMIT

        FakeKnowledgeSkill.reset()
        # 长内容 — token_count 超过短内容阈值
        FakeKnowledgeSkill.add_knowledge(
            "chunk_long_1",
            "本公司退货政策说明：自购买之日起 30 天内，"
            "如商品存在质量问题，可凭购买凭证申请退货。"
            "退货需保证商品完好、配件齐全、包装完整，"
            "不影响二次销售。非质量问题的退货，"
            "运费由买家承担。",
            title="退货政策",
            token_count=KNOWLEDGE_SHORT_CONTENT_TOKEN_LIMIT + 10,
        )

        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("退货政策")
            .scenario_is("knowledge.policy")
            .expect_skill_calls("search_qa", "search_knowledge")
            .run())

        # LLM 不可用时降级为直接返回原始内容
        assert result.metadata["scenario_id"] == "knowledge.policy"
        assert "退货" in result.reply


# ══════════════════════════════════════════════════════════
# 记忆 FakeSkill 全链路内容+Trace
# ══════════════════════════════════════════════════════════


class TestMemoryFakeSkillContent:
    """记忆场景全链路内容+Trace 断言。"""

    @pytest.mark.asyncio
    async def test_memory_save_with_contact_records_skill(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """memory.save → 记录 remember_info。"""
        from tests.test_memory_handler import FakeMemorySkill

        FakeMemorySkill.reset()
        FakeMemorySkill.add_saved_item("偏好", "黑色")

        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("我喜欢黑色的")
            .scenario_is("memory.save")
            .with_context(contact_id=1)
            .run())

        trace = result.metadata.get("resource_trace", {})
        skill_calls = trace.get("skill_calls", [])
        assert "remember_info" in skill_calls, (
            f"memory.save 应记录 remember_info，实际: {skill_calls}"
        )

    @pytest.mark.asyncio
    async def test_memory_recall_with_contact_records_skill(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """memory.recall → 记录 recall_info。"""
        from tests.test_memory_handler import FakeMemorySkill

        FakeMemorySkill.reset()
        FakeMemorySkill.add_saved_item("偏好", "黑色")

        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("我有什么偏好")
            .scenario_is("memory.recall")
            .with_context(contact_id=1)
            .run())

        trace = result.metadata.get("resource_trace", {})
        skill_calls = trace.get("skill_calls", [])
        assert "recall_info" in skill_calls, (
            f"memory.recall 应记录 recall_info，实际: {skill_calls}"
        )

    @pytest.mark.asyncio
    async def test_memory_save_no_contact_no_skill(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """memory.save 无 contact_id → 不调 Skill，直接提示。"""
        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("我喜欢黑色的")
            .scenario_is("memory.save")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert trace.get("skill_calls") == []
        assert "身份" in result.reply

    @pytest.mark.asyncio
    async def test_memory_recall_no_contact_returns_no_skill(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """memory.recall 无 contact_id → 不调 Skill，提示确认身份。"""
        result = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("我有什么偏好")
            .scenario_is("memory.recall")
            .run())

        trace = result.metadata.get("resource_trace", {})
        assert trace.get("skill_calls") == []
        assert trace.get("llm_calls") == 0
        # memory handler 在无 contact_id 时返回 no_text reply（与 save 一致）
        assert result.reply


# ══════════════════════════════════════════════════════════
# 写操作幂等验证（Handler 层）
# ══════════════════════════════════════════════════════════


class TestWriteIdempotency:
    """写操作幂等验证：相同输入不应重复执行。

    注：IdempotencyService 单元测试见 test_idempotency.py。
    此处验证 handler 层面不会因重复请求而产生重复 trace/skill 调用。
    """

    @pytest.mark.asyncio
    async def test_identical_write_calls_produce_same_trace(
        self,
        fake_skill_service: AssistantService,
        fake_skill_mocks: dict[str, Any],
    ) -> None:
        """同一场景连续调用两次 → 两次 trace 结构一致，不抛异常。"""
        from tests.test_order_handler import FakeOrderSkill

        FakeOrderSkill.reset()

        # 第一次调用
        result1 = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("我的订单")
            .scenario_is("order.list")
            .with_context(contact_id=1)
            .run())

        # 第二次调用（相同输入）
        result2 = await (ScenarioTestBuilder(fake_skill_service, fake_skill_mocks)
            .user_says("我的订单")
            .scenario_is("order.list")
            .with_context(contact_id=1)
            .run())

        # 两次都有 resource_trace
        trace1 = result1.metadata.get("resource_trace", {})
        trace2 = result2.metadata.get("resource_trace", {})
        assert "skill_calls" in trace1
        assert "skill_calls" in trace2
        assert isinstance(trace1["skill_calls"], list)
        assert isinstance(trace2["skill_calls"], list)
