"""Phase 9 Agent DIRECT_SKILL 最小闭环单元测试。

测试覆盖：
  - types: ExecutionMode, ToolResult, PlannedToolCall
  - skill_registry: alias 解析、注册检查
  - nodes: decide / plan / dispatch / generate_reply / post_process / build_context
  - graph: 端到端 + 3 个验收场景
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.agent.nodes import (
    _extract_customer_text,
    _template_fallback,
    build_context,
    decide_execution_mode,
    dispatch_tools,
    generate_reply,
    plan_tools_from_routed_intent,
    post_process,
)
from app.services.ai.agent.skill_registry import (
    MCP_TOOL_NAMES,
    SIDEEFFECT_SKILLS,
    SKILL_ALIASES,
    SKILL_REGISTRY,
    is_skill_registered,
    resolve_skill,
)
from app.services.ai.agent.types import (
    AgentContext,
    AgentState,
    ExecutionMode,
    ToolResult,
)
from app.services.ai.intent.types import IntentHit, RoutedIntent

# ============================================================================
# 测试夹具
# ============================================================================


def _make_routed(intent_skill, confidence=0.92, route="AGENT", skill=None, multi=False, ambiguous=False):
    """快速构造 RoutedIntent。intent_skill 同时作为 intent 和默认 skill。"""
    actual_skill = skill if skill is not None else intent_skill
    hits = [_make_hit(intent=intent_skill, skill=actual_skill, confidence=confidence, ambiguous=ambiguous)]
    if multi:
        hits.append(_make_hit(intent="product_stock", skill=actual_skill, confidence=0.90))
    return RoutedIntent(
        primary_intent=intent_skill,
        confidence=confidence,
        route=route,
        skill=actual_skill,
        hits=hits,
        is_multi_intent=multi or len(hits) > 1,
        need_clarification=False,
        reason="test",
    )


def _make_hit(intent="product_search", skill="search_products", confidence=0.92, ambiguous=False):
    return IntentHit(
        segment="你们有什么茶叶",
        intent=intent,
        label="商品搜索",
        confidence=confidence,
        route="AGENT",
        skill=skill,
        ambiguous=ambiguous,
        reason="test hit",
    )


def _make_agent_ctx(db=None):
    if db is None:
        db = AsyncMock()
        db.execute = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()
    return AgentContext(
        db=db,
        tenant_id=1,
        conversation_id=100,
        contact_id=200,
    )


def _base_state(routed=None):
    routed = routed or _make_routed("product_search")
    return {
        "tenant_id": 1,
        "conversation_id": 100,
        "contact_id": 200,
        "execution_mode": "",
        "planned_tool_calls": [],
        "tool_results": [],
        "tool_call_count": 0,
        "final_reply": None,
        "error": None,
        "messages": [{"role": "user", "content": "你们有什么茶叶"}],
    }


def _make_config(ctx=None, routed=None):
    if ctx is None:
        ctx = _make_agent_ctx()
    if routed is None:
        routed = _make_routed("product_search")
    return {"configurable": {"agent_context": ctx, "routed_intent": routed}}


# ============================================================================
# Types 测试
# ============================================================================


class TestExecutionMode:
    def test_enum_values(self):
        assert ExecutionMode.DIRECT_SKILL.value == "direct_skill"
        assert ExecutionMode.AGENT_PLANNER.value == "agent_planner"
        assert ExecutionMode.CLARIFY.value == "clarify"
        assert ExecutionMode.HUMAN.value == "human"

    def test_enum_is_string(self):
        assert isinstance(ExecutionMode.DIRECT_SKILL, str)


class TestToolResult:
    def test_ok_result(self):
        r = ToolResult(ok=True, skill_name="search_products", result={"products": []})
        assert r.ok is True
        assert r.result == {"products": []}
        assert r.error is None

    def test_error_result(self):
        r = ToolResult(ok=False, skill_name="bad_skill", error="Unknown skill")
        assert r.ok is False
        assert r.error == "Unknown skill"

    def test_immutable(self):
        r = ToolResult(ok=True, skill_name="test", result="ok")
        with pytest.raises(Exception):
            r.ok = False


class TestAgentState:
    def test_dict_operations(self):
        state = AgentState({"key": "value"})
        assert state["key"] == "value"
        state["new_key"] = 123
        assert state["new_key"] == 123


# ============================================================================
# Skill Registry 测试
# ============================================================================


class TestSkillRegistry:
    def test_all_real_skills_registered(self):
        for skill_name in ["get_store_showcase", "search_products", "remember_info"]:
            assert skill_name in SKILL_REGISTRY, f"{skill_name} 未注册"

    def test_all_stub_skills_registered(self):
        for skill_name in [
            "create_order", "confirm_order", "manage_order",
            "update_price_strategy", "list_documents", "manage_todos",
        ]:
            assert skill_name in SKILL_REGISTRY, f"stub {skill_name} 未注册"

    def test_all_mcp_stubs_registered(self):
        for skill_name in ["search_knowledge", "search_images"]:
            assert skill_name in SKILL_REGISTRY, f"MCP {skill_name} 未注册"
            assert skill_name in MCP_TOOL_NAMES

    def test_registry_count(self):
        assert len(SKILL_REGISTRY) == 11


class TestResolveSkill:
    def test_direct_match(self):
        assert resolve_skill("search_products") == "search_products"
        assert resolve_skill("get_store_showcase") == "get_store_showcase"

    def test_alias_mapping(self):
        assert resolve_skill("product_price") == "search_products"
        assert resolve_skill("product_stock") == "search_products"
        assert resolve_skill("delivery_time") == "search_products"

    def test_order_aliases(self):
        assert resolve_skill("order_status") == "manage_order"
        assert resolve_skill("logistics_status") == "manage_order"
        assert resolve_skill("invoice") == "manage_order"

    def test_human_service_returns_none(self):
        assert resolve_skill("human_service") is None

    def test_none_input(self):
        assert resolve_skill(None) is None

    def test_empty_input(self):
        assert resolve_skill("") is None

    def test_unknown_skill(self):
        assert resolve_skill("nonexistent_skill") is None


class TestIsSkillRegistered:
    def test_registered(self):
        assert is_skill_registered("search_products") is True
        assert is_skill_registered("product_price") is True  # alias

    def test_not_registered(self):
        assert is_skill_registered("nonexistent") is False
        assert is_skill_registered("human_service") is False  # maps to None

    def test_none_input(self):
        assert is_skill_registered(None) is False


class TestSkillAliases:
    def test_all_values_in_registry_or_none(self):
        for intent_skill, registry_key in SKILL_ALIASES.items():
            if registry_key is None:
                assert intent_skill == "human_service"
            else:
                assert registry_key in SKILL_REGISTRY, (
                    f"SKILL_ALIASES[{intent_skill}]={registry_key} 不在 SKILL_REGISTRY 中"
                )

    def test_sideeffect_skills(self):
        assert "create_order" in SIDEEFFECT_SKILLS
        assert "manage_order" in SIDEEFFECT_SKILLS
        assert "search_products" not in SIDEEFFECT_SKILLS


# ============================================================================
# Nodes 测试
# ============================================================================


class TestBuildContext:
    @pytest.mark.asyncio
    async def test_sets_state_correctly(self):
        routed = _make_routed("product_search")
        ctx = _make_agent_ctx()
        config = _make_config(ctx=ctx, routed=routed)

        state = AgentState({})
        result = await build_context(state, config=config)

        assert result["tenant_id"] == 1
        assert result["conversation_id"] == 100
        assert result["contact_id"] == 200
        assert result["execution_mode"] == ""
        assert result["planned_tool_calls"] == []
        assert result["tool_call_count"] == 0
        assert result["final_reply"] is None
        assert result["messages"][0]["role"] == "user"


class TestDecideExecutionMode:
    @pytest.mark.asyncio
    async def test_low_confidence_clarify(self):
        routed = _make_routed("chitchat", confidence=0.3, route="GENERAL_REPLY")
        result = await decide_execution_mode(_base_state(), config=_make_config(routed=routed))
        assert result["execution_mode"] == ExecutionMode.CLARIFY.value

    @pytest.mark.asyncio
    async def test_no_hits_clarify(self):
        routed = RoutedIntent(
            primary_intent="unknown_intent", confidence=0.0, route="GENERAL_REPLY",
            skill=None, hits=[], is_multi_intent=False, need_clarification=False, reason="test",
        )
        result = await decide_execution_mode(_base_state(), config=_make_config(routed=routed))
        assert result["execution_mode"] == ExecutionMode.CLARIFY.value

    @pytest.mark.asyncio
    async def test_direct_skill_single_high_confidence(self):
        routed = _make_routed("product_search", confidence=0.92)
        result = await decide_execution_mode(_base_state(), config=_make_config(routed=routed))
        assert result["execution_mode"] == ExecutionMode.DIRECT_SKILL.value

    @pytest.mark.asyncio
    async def test_agent_planner_medium_confidence(self):
        routed = _make_routed("product_search", confidence=0.70)
        result = await decide_execution_mode(_base_state(), config=_make_config(routed=routed))
        assert result["execution_mode"] == ExecutionMode.AGENT_PLANNER.value

    @pytest.mark.asyncio
    async def test_agent_planner_ambiguous(self):
        routed = _make_routed("product_search", confidence=0.92, ambiguous=True)
        result = await decide_execution_mode(_base_state(), config=_make_config(routed=routed))
        assert result["execution_mode"] == ExecutionMode.AGENT_PLANNER.value

    @pytest.mark.asyncio
    async def test_agent_planner_sideeffect_skill(self):
        routed = _make_routed("create_order", confidence=0.92, skill="create_order")
        result = await decide_execution_mode(_base_state(), config=_make_config(routed=routed))
        assert result["execution_mode"] == ExecutionMode.AGENT_PLANNER.value

    @pytest.mark.asyncio
    async def test_direct_skill_multi_all_high_confidence(self):
        routed = _make_routed("product_price", confidence=0.92, multi=True)
        result = await decide_execution_mode(_base_state(), config=_make_config(routed=routed))
        assert result["execution_mode"] == ExecutionMode.DIRECT_SKILL.value

    @pytest.mark.asyncio
    async def test_agent_planner_multi_one_low(self):
        hit1 = _make_hit(intent="product_price", skill="search_products", confidence=0.92)
        hit2 = _make_hit(intent="product_stock", skill="search_products", confidence=0.60)
        routed = RoutedIntent(
            primary_intent="product_price", confidence=0.92, route="AGENT",
            skill="search_products", hits=[hit1, hit2],
            is_multi_intent=True, need_clarification=False, reason="test",
        )
        result = await decide_execution_mode(_base_state(), config=_make_config(routed=routed))
        assert result["execution_mode"] == ExecutionMode.AGENT_PLANNER.value


class TestPlanTools:
    @pytest.mark.asyncio
    async def test_direct_skill_single(self):
        routed = _make_routed("product_search", confidence=0.92)
        state = _base_state()
        state["execution_mode"] = ExecutionMode.DIRECT_SKILL.value
        result = await plan_tools_from_routed_intent(state, config=_make_config(routed=routed))
        assert len(result["planned_tool_calls"]) == 1
        assert result["planned_tool_calls"][0]["skill_name"] == "search_products"

    @pytest.mark.asyncio
    async def test_direct_skill_multi(self):
        routed = _make_routed("product_price", confidence=0.92, multi=True)
        state = _base_state()
        state["execution_mode"] = ExecutionMode.DIRECT_SKILL.value
        result = await plan_tools_from_routed_intent(state, config=_make_config(routed=routed))
        assert len(result["planned_tool_calls"]) == 2
        assert result["planned_tool_calls"][0]["skill_name"] == "search_products"
        assert result["planned_tool_calls"][1]["skill_name"] == "search_products"

    @pytest.mark.asyncio
    async def test_direct_skill_with_alias(self):
        routed = _make_routed("product_price", confidence=0.92)
        state = _base_state()
        state["execution_mode"] = ExecutionMode.DIRECT_SKILL.value
        result = await plan_tools_from_routed_intent(state, config=_make_config(routed=routed))
        assert result["planned_tool_calls"][0]["skill_name"] == "search_products"

    @pytest.mark.asyncio
    async def test_skip_unknown_skill(self):
        routed = RoutedIntent(
            primary_intent="unknown_skill", confidence=0.92, route="AGENT",
            skill="nonexistent", hits=[_make_hit(intent="unknown_skill", skill="nonexistent")],
            is_multi_intent=False, need_clarification=False, reason="test",
        )
        state = _base_state()
        state["execution_mode"] = ExecutionMode.DIRECT_SKILL.value
        result = await plan_tools_from_routed_intent(state, config=_make_config(routed=routed))
        assert len(result["planned_tool_calls"]) == 0

    @pytest.mark.asyncio
    async def test_human_service_skipped(self):
        routed = RoutedIntent(
            primary_intent="human_service", confidence=0.92, route="AGENT",
            skill="human_service", hits=[_make_hit(intent="human_service", skill="human_service")],
            is_multi_intent=False, need_clarification=False, reason="test",
        )
        state = _base_state()
        state["execution_mode"] = ExecutionMode.DIRECT_SKILL.value
        result = await plan_tools_from_routed_intent(state, config=_make_config(routed=routed))
        assert len(result["planned_tool_calls"]) == 0

    @pytest.mark.asyncio
    async def test_agent_planner_empty_plans(self):
        state = _base_state()
        state["execution_mode"] = ExecutionMode.AGENT_PLANNER.value
        result = await plan_tools_from_routed_intent(state)
        assert result["planned_tool_calls"] == []


class TestDispatchTools:
    @pytest.mark.asyncio
    async def test_call_real_store_skill(self):
        state = _base_state()
        state["execution_mode"] = ExecutionMode.DIRECT_SKILL.value
        state["planned_tool_calls"] = [{
            "skill_name": "get_store_showcase",
            "arguments": {},
            "source": "intent_route",
            "reason": "test",
        }]
        ctx = _make_agent_ctx()

        config = {"configurable": {"agent_context": ctx}}
        result = await dispatch_tools(state, config=config)

        assert result["tool_call_count"] == 1
        assert result["tool_results"][0]["ok"] is True
        assert result["tool_results"][0]["skill_name"] == "get_store_showcase"
        assert "FastAgent" in str(result["tool_results"][0]["result"])

    @pytest.mark.asyncio
    async def test_call_stub_skill(self):
        state = _base_state()
        state["execution_mode"] = ExecutionMode.DIRECT_SKILL.value
        state["planned_tool_calls"] = [{
            "skill_name": "create_order",
            "arguments": {},
            "source": "intent_route",
            "reason": "test",
        }]
        ctx = _make_agent_ctx()
        config = {"configurable": {"agent_context": ctx}}

        result = await dispatch_tools(state, config=config)

        assert result["tool_call_count"] == 1
        assert result["tool_results"][0]["ok"] is True
        assert "即将上线" in str(result["tool_results"][0]["result"])

    @pytest.mark.asyncio
    async def test_unknown_skill_returns_error(self):
        state = _base_state()
        state["planned_tool_calls"] = [{
            "skill_name": "nonexistent_skill",
            "arguments": {},
            "source": "intent_route",
            "reason": "test",
        }]
        ctx = _make_agent_ctx()
        config = {"configurable": {"agent_context": ctx}}

        result = await dispatch_tools(state, config=config)

        assert result["tool_results"][0]["ok"] is False
        assert "Unknown skill" in str(result["tool_results"][0]["error"])

    @pytest.mark.asyncio
    async def test_respects_max_limit(self):
        state = _base_state()
        state["tool_call_count"] = 2  # near limit (default max=3)
        state["planned_tool_calls"] = [
            {"skill_name": "get_store_showcase", "arguments": {}, "source": "intent_route", "reason": "test"},
            {"skill_name": "get_store_showcase", "arguments": {}, "source": "intent_route", "reason": "test"},
        ]
        ctx = _make_agent_ctx()
        config = {"configurable": {"agent_context": ctx}}

        result = await dispatch_tools(state, config=config)

        # Should only execute 1 more (3 - 2 = 1)
        assert result["tool_call_count"] <= 3


class TestGenerateReply:
    @pytest.mark.asyncio
    async def test_agent_planner_stub_reply(self):
        state = _base_state()
        state["execution_mode"] = ExecutionMode.AGENT_PLANNER.value
        result = await generate_reply(state)
        assert "转接人工客服" in result["final_reply"]

    @pytest.mark.asyncio
    async def test_clarify_generates_reply(self):
        state = _base_state()
        state["execution_mode"] = ExecutionMode.CLARIFY.value

        with patch("app.services.ai.agent.nodes.LLMClient") as mock_client:
            mock_client.return_value.complete = AsyncMock(
                return_value="请问您想了解什么产品呢？"
            )
            result = await generate_reply(state)

        assert len(result["final_reply"]) > 0

    @pytest.mark.asyncio
    async def test_clarify_fallback_on_llm_error(self):
        state = _base_state()
        state["execution_mode"] = ExecutionMode.CLARIFY.value

        with patch("app.services.ai.agent.nodes.LLMClient") as mock_client:
            from app.integrations.llm_client import LLMClientError
            mock_client.return_value.complete = AsyncMock(
                side_effect=LLMClientError("service down")
            )
            result = await generate_reply(state)

        assert len(result["final_reply"]) > 0  # fallback message

    @pytest.mark.asyncio
    async def test_direct_skill_with_tool_results(self):
        state = _base_state()
        state["execution_mode"] = ExecutionMode.DIRECT_SKILL.value
        state["tool_results"] = [{
            "skill_name": "get_store_showcase",
            "ok": True,
            "result": "FastAgent 智能茶庄，主营绿茶、红茶、乌龙茶...",
            "error": None,
        }]

        with patch("app.services.ai.agent.nodes.LLMClient") as mock_client:
            mock_client.return_value.complete = AsyncMock(
                return_value="您好！我们是FastAgent智能茶庄，主营绿茶、红茶、乌龙茶等多种高品质茶叶。"
            )
            result = await generate_reply(state)

        assert len(result["final_reply"]) > 0

    @pytest.mark.asyncio
    async def test_direct_skill_fallback_on_llm_error(self):
        state = _base_state()
        state["execution_mode"] = ExecutionMode.DIRECT_SKILL.value
        state["tool_results"] = [{
            "skill_name": "get_store_showcase",
            "ok": True,
            "result": "FastAgent 智能茶庄",
            "error": None,
        }]

        with patch("app.services.ai.agent.nodes.LLMClient") as mock_client:
            from app.integrations.llm_client import LLMClientError
            mock_client.return_value.complete = AsyncMock(
                side_effect=LLMClientError("service down")
            )
            result = await generate_reply(state)

        assert "FastAgent 智能茶庄" in result["final_reply"]

    @pytest.mark.asyncio
    async def test_no_tool_results_fallback(self):
        state = _base_state()
        state["execution_mode"] = ExecutionMode.DIRECT_SKILL.value
        state["tool_results"] = []

        with patch("app.services.ai.agent.nodes.LLMClient") as mock_client:
            mock_client.return_value.complete = AsyncMock(
                return_value="您好，请问有什么可以帮您的？"
            )
            result = await generate_reply(state)

        assert len(result["final_reply"]) > 0


class TestPostProcess:
    @pytest.mark.asyncio
    async def test_clean_reply(self):
        state = _base_state()
        state["final_reply"] = "  您好，欢迎光临！  "
        result = await post_process(state)
        assert result["final_reply"] == "您好，欢迎光临！"

    @pytest.mark.asyncio
    async def test_strip_prefix(self):
        state = _base_state()
        state["final_reply"] = "客服：您好，欢迎光临！"
        result = await post_process(state)
        assert not result["final_reply"].startswith("客服：")

    @pytest.mark.asyncio
    async def test_empty_reply_fallback(self):
        state = _base_state()
        state["execution_mode"] = ExecutionMode.DIRECT_SKILL.value
        state["final_reply"] = ""
        result = await post_process(state)
        assert len(result["final_reply"]) > 0

    @pytest.mark.asyncio
    async def test_empty_clarify_fallback(self):
        state = _base_state()
        state["execution_mode"] = ExecutionMode.CLARIFY.value
        state["final_reply"] = ""
        result = await post_process(state)
        assert len(result["final_reply"]) > 0

    @pytest.mark.asyncio
    async def test_empty_agent_planner_fallback(self):
        state = _base_state()
        state["execution_mode"] = ExecutionMode.AGENT_PLANNER.value
        state["final_reply"] = ""
        result = await post_process(state)
        assert "转接人工" in result["final_reply"]


class TestHelpers:
    def test_extract_customer_text(self):
        routed = RoutedIntent(
            primary_intent="product_search",
            confidence=0.92,
            route="AGENT",
            skill="search_products",
            hits=[_make_hit()],
        )
        text = _extract_customer_text(routed)
        assert "你们有什么茶叶" in text

    def test_template_fallback_success(self):
        results = [{"ok": True, "skill_name": "s1", "result": "结果1"}]
        reply = _template_fallback(results)
        assert "结果1" in reply

    def test_template_fallback_all_fail(self):
        results = [{"ok": False, "skill_name": "s1", "error": "fail"}]
        reply = _template_fallback(results)
        assert "暂时无法处理" in reply

    def test_template_fallback_dict_with_message(self):
        results = [{"ok": True, "skill_name": "s1", "result": {"message": "功能即将上线"}}]
        reply = _template_fallback(results)
        assert "功能即将上线" in reply


# ============================================================================
# 3 个验收场景
# ============================================================================


class TestScenarioA_ProductSearch:
    """场景 A: "你们有什么茶叶" → DIRECT_SKILL → search_products → 商品推荐"""

    @pytest.mark.asyncio
    async def test_decide_is_direct_skill(self):
        routed = _make_routed("product_search", confidence=0.92)
        result = await decide_execution_mode(_base_state(), config=_make_config(routed=routed))
        assert result["execution_mode"] == ExecutionMode.DIRECT_SKILL.value

    @pytest.mark.asyncio
    async def test_plan_maps_to_search_products(self):
        routed = _make_routed("product_search", confidence=0.92)
        state = _base_state()
        state["execution_mode"] = ExecutionMode.DIRECT_SKILL.value
        result = await plan_tools_from_routed_intent(state, config=_make_config(routed=routed))
        assert result["planned_tool_calls"][0]["skill_name"] == "search_products"

    @pytest.mark.asyncio
    async def test_end_to_end(self):
        """端到端：build_context → decide → plan → dispatch → generate_reply → post_process"""
        routed = _make_routed("search_products", confidence=0.92)
        ctx = _make_agent_ctx()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        ctx.db.execute = AsyncMock(return_value=mock_result)

        # build_context
        config = _make_config(ctx=ctx, routed=routed)
        state = await build_context(AgentState({}), config=config)
        assert state["tenant_id"] == 1

        # decide
        state = await decide_execution_mode(state, config=config)
        assert state["execution_mode"] == ExecutionMode.DIRECT_SKILL.value

        # plan
        state = await plan_tools_from_routed_intent(state, config=config)
        assert len(state["planned_tool_calls"]) == 1
        assert state["planned_tool_calls"][0]["skill_name"] == "search_products"

        # dispatch (real skill call with mocked DB)
        state = await dispatch_tools(state, config=config)
        assert state["tool_call_count"] == 1
        assert state["tool_results"][0]["ok"] is True

        # generate_reply (mock LLM)
        with patch("app.services.ai.agent.nodes.LLMClient") as mock_client:
            mock_client.return_value.complete = AsyncMock(
                return_value="您好！我们目前有龙井、碧螺春、铁观音等多种茶叶，请问您喜欢什么类型的？"
            )
            state = await generate_reply(state)

        assert len(state["final_reply"]) > 0

        # post_process
        state = await post_process(state)
        assert len(state["final_reply"]) > 0
        assert state["error"] is None


class TestScenarioB_MultiIntent:
    """场景 B: "这个多少钱？有货吗？" → DIRECT_SKILL → 2 个 PlannedToolCall"""

    @pytest.mark.asyncio
    async def test_multi_hit_all_direct_skill(self):
        routed = _make_routed("product_price", confidence=0.92, multi=True)
        result = await decide_execution_mode(_base_state(), config=_make_config(routed=routed))
        assert result["execution_mode"] == ExecutionMode.DIRECT_SKILL.value

    @pytest.mark.asyncio
    async def test_plan_generates_two_calls(self):
        routed = _make_routed("product_price", confidence=0.92, multi=True)
        state = _base_state()
        state["execution_mode"] = ExecutionMode.DIRECT_SKILL.value
        result = await plan_tools_from_routed_intent(state, config=_make_config(routed=routed))
        assert len(result["planned_tool_calls"]) == 2
        for plan in result["planned_tool_calls"]:
            assert plan["skill_name"] == "search_products"

    @pytest.mark.asyncio
    async def test_end_to_end_multi(self):
        routed = _make_routed("product_price", confidence=0.92, multi=True)
        ctx = _make_agent_ctx()
        config = _make_config(ctx=ctx, routed=routed)

        state = await build_context(AgentState({}), config=config)
        state = await decide_execution_mode(state, config=config)
        assert state["execution_mode"] == ExecutionMode.DIRECT_SKILL.value

        state = await plan_tools_from_routed_intent(state, config=config)
        assert len(state["planned_tool_calls"]) == 2

        state = await dispatch_tools(state, config=config)
        assert state["tool_call_count"] == 2

        with patch("app.services.ai.agent.nodes.LLMClient") as mock_client:
            mock_client.return_value.complete = AsyncMock(
                return_value="您好！该商品目前有货，价格为128元。今天可以发货。"
            )
            state = await generate_reply(state)

        state = await post_process(state)
        assert len(state["final_reply"]) > 0


# ============================================================================
# 图端到端测试（无 LLM）
# ============================================================================


class TestAgentGraph:
    """测试 compiled graph 能否正确执行（mock LLM）。"""

    @pytest.mark.asyncio
    async def test_graph_direct_skill_path(self):
        from app.services.ai.agent.graph import build_agent_graph

        routed = _make_routed("product_search", confidence=0.92)
        ctx = _make_agent_ctx()
        config = _make_config(ctx=ctx, routed=routed)

        graph = build_agent_graph()

        with patch("app.services.ai.agent.nodes.LLMClient") as mock_client:
            mock_client.return_value.complete = AsyncMock(
                return_value="您好！我们有多款茶叶可供选择，欢迎选购。"
            )
            result = await graph.ainvoke({}, config=config)

        assert result["execution_mode"] == ExecutionMode.DIRECT_SKILL.value
        assert result["tool_call_count"] >= 1
        assert len(result["final_reply"]) > 0

    @pytest.mark.asyncio
    async def test_graph_clarify_path(self):
        from app.services.ai.agent.graph import build_agent_graph

        routed = _make_routed("chitchat", confidence=0.3, route="AGENT")
        ctx = _make_agent_ctx()
        config = _make_config(ctx=ctx, routed=routed)

        graph = build_agent_graph()

        with patch("app.services.ai.agent.nodes.LLMClient") as mock_client:
            mock_client.return_value.complete = AsyncMock(
                return_value="请问您想了解我们的产品吗？"
            )
            result = await graph.ainvoke({}, config=config)

        assert result["execution_mode"] == ExecutionMode.CLARIFY.value
        assert result["tool_call_count"] == 0
        assert len(result["final_reply"]) > 0

    @pytest.mark.asyncio
    async def test_graph_conditional_routing(self):
        """验证 decide 后的条件边正确路由。"""
        from app.services.ai.agent.graph import _route_after_decide

        # DIRECT_SKILL → plan_tools
        state = AgentState({"execution_mode": ExecutionMode.DIRECT_SKILL.value})
        assert _route_after_decide(state) == "plan_tools_from_routed_intent"

        # AGENT_PLANNER → plan_tools
        state = AgentState({"execution_mode": ExecutionMode.AGENT_PLANNER.value})
        assert _route_after_decide(state) == "plan_tools_from_routed_intent"

        # CLARIFY → generate_reply
        state = AgentState({"execution_mode": ExecutionMode.CLARIFY.value})
        assert _route_after_decide(state) == "generate_reply"
