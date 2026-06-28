"""ScenarioSpec 校验单元测试。

覆盖 PolicyGuard 的 7 种越权检测 + 无越权正常路径。
"""
from __future__ import annotations

from typing import Any

import pytest

from app.ai.context.pending_state import PendingDirective
from app.ai.handlers.base import HandlerResult, ResourceTrace
from app.ai.scenario.policy_guard import PolicyGuard, PolicyViolation
from app.ai.scenario.spec import ScenarioSpec, get_spec, is_write_skill


# ══════════════════════════════════════════════
# PolicyGuard 单元测试
# ══════════════════════════════════════════════


class TestPolicyGuardSkillValidation:
    """Skill 越权校验。"""

    def test_allowed_skill_passes(self) -> None:
        spec = ScenarioSpec(scenario_id="test", allowed_skills=["search_products"])
        result = HandlerResult(
            scenario_id="test",
            reply="ok",
            pending_directive=PendingDirective.CLEAR,
        )
        result.resource_trace = ResourceTrace(
            scenario_id="test",
            skill_calls=["search_products"],
        )

        violations = PolicyGuard.validate_result(spec, result)
        assert len(violations) == 0

    def test_disallowed_skill_triggers_violation(self) -> None:
        spec = ScenarioSpec(scenario_id="test", allowed_skills=["get_detail"])
        result = HandlerResult(
            scenario_id="test",
            reply="ok",
            pending_directive=PendingDirective.CLEAR,
        )
        result.resource_trace = ResourceTrace(
            scenario_id="test",
            skill_calls=["search_products"],
        )

        violations = PolicyGuard.validate_result(spec, result)
        codes = [v.code for v in violations]
        assert "SKILL_NOT_ALLOWED" in codes

    def test_multiple_disallowed_skills_all_reported(self) -> None:
        spec = ScenarioSpec(scenario_id="test", allowed_skills=["get_detail"])
        result = HandlerResult(
            scenario_id="test",
            reply="ok",
            pending_directive=PendingDirective.CLEAR,
        )
        result.resource_trace = ResourceTrace(
            scenario_id="test",
            skill_calls=["search_products", "remember_info"],
        )

        violations = PolicyGuard.validate_result(spec, result)
        skill_codes = [v for v in violations if v.code == "SKILL_NOT_ALLOWED"]
        assert len(skill_codes) == 2

    def test_no_allowed_skills_and_none_called_passes(self) -> None:
        spec = ScenarioSpec(scenario_id="test", allowed_skills=[])
        result = HandlerResult(
            scenario_id="test",
            reply="hello",
            pending_directive=PendingDirective.CLEAR,
        )
        result.resource_trace = ResourceTrace(scenario_id="test")

        violations = PolicyGuard.validate_result(spec, result)
        assert len(violations) == 0


class TestPolicyGuardRiskLevel:
    """Risk level 越权校验。"""

    def test_read_only_with_write_skill_triggers_violation(self) -> None:
        spec = ScenarioSpec(scenario_id="test", risk_level="read_only")
        result = HandlerResult(
            scenario_id="test",
            reply="ok",
            pending_directive=PendingDirective.CLEAR,
        )
        result.resource_trace = ResourceTrace(
            scenario_id="test",
            skill_calls=["remember_info"],  # 写 Skill
        )

        violations = PolicyGuard.validate_result(spec, result)
        codes = [v.code for v in violations]
        assert "READ_ONLY_WRITE_SKILL" in codes

    def test_read_only_with_read_skill_passes(self) -> None:
        spec = ScenarioSpec(scenario_id="test", risk_level="read_only", allowed_skills=["search_products"])
        result = HandlerResult(
            scenario_id="test",
            reply="ok",
            pending_directive=PendingDirective.CLEAR,
        )
        result.resource_trace = ResourceTrace(
            scenario_id="test",
            skill_calls=["search_products"],
        )

        violations = PolicyGuard.validate_result(spec, result)
        read_only_codes = [v for v in violations if "READ_ONLY" in v.code]
        assert len(read_only_codes) == 0

    def test_read_only_set_pending_triggers_violation(self) -> None:
        spec = ScenarioSpec(scenario_id="test", risk_level="read_only")
        result = HandlerResult(
            scenario_id="test",
            reply="ok",
            pending_directive=PendingDirective.SET,
        )
        result.resource_trace = ResourceTrace(scenario_id="test")

        violations = PolicyGuard.validate_result(spec, result)
        codes = [v.code for v in violations]
        assert "READ_ONLY_SET_PENDING" in codes

    def test_human_required_non_transfer_triggers_violation(self) -> None:
        spec = ScenarioSpec(scenario_id="test", risk_level="human_required")
        result = HandlerResult(
            scenario_id="product.detail",
            reply="detail",
            pending_directive=PendingDirective.CLEAR,
        )
        result.resource_trace = ResourceTrace(scenario_id="product.detail")

        violations = PolicyGuard.validate_result(spec, result)
        codes = [v.code for v in violations]
        assert "HUMAN_REQUIRED_AUTO_EXEC" in codes

    def test_human_required_with_transfer_passes(self) -> None:
        spec = ScenarioSpec(scenario_id="human.transfer", risk_level="human_required")
        result = HandlerResult(
            scenario_id="human.transfer",
            reply="转人工",
            pending_directive=PendingDirective.CLEAR,
        )
        result.resource_trace = ResourceTrace(scenario_id="human.transfer")

        violations = PolicyGuard.validate_result(spec, result)
        assert len(violations) == 0


class TestPolicyGuardLLM:
    """LLM 越权校验。"""

    def test_llm_calls_without_allowance_triggers_violation(self) -> None:
        spec = ScenarioSpec(scenario_id="test")
        result = HandlerResult(
            scenario_id="test", reply="ok", pending_directive=PendingDirective.CLEAR,
        )
        result.resource_trace = ResourceTrace(scenario_id="test", llm_calls=2)

        violations = PolicyGuard.validate_result(spec, result)
        codes = [v.code for v in violations]
        assert "LLM_NOT_ALLOWED" in codes

    def test_llm_calls_with_entity_extraction_allowance_passes(self) -> None:
        spec = ScenarioSpec(scenario_id="test", allow_llm_entity_extraction=True)
        result = HandlerResult(
            scenario_id="test", reply="ok", pending_directive=PendingDirective.CLEAR,
        )
        result.resource_trace = ResourceTrace(scenario_id="test", llm_calls=2)

        violations = PolicyGuard.validate_result(spec, result)
        llm_codes = [v for v in violations if v.code == "LLM_NOT_ALLOWED"]
        assert len(llm_codes) == 0

    def test_no_llm_calls_no_violation(self) -> None:
        spec = ScenarioSpec(scenario_id="test")
        result = HandlerResult(
            scenario_id="test", reply="ok", pending_directive=PendingDirective.CLEAR,
        )
        result.resource_trace = ResourceTrace(scenario_id="test", llm_calls=0)

        violations = PolicyGuard.validate_result(spec, result)
        llm_codes = [v for v in violations if "LLM" in v.code]
        assert len(llm_codes) == 0


class TestPolicyGuardVector:
    """Vector 越权校验。"""

    def test_vector_calls_without_allowance_triggers_violation(self) -> None:
        spec = ScenarioSpec(scenario_id="test")
        result = HandlerResult(
            scenario_id="test", reply="ok", pending_directive=PendingDirective.CLEAR,
        )
        result.resource_trace = ResourceTrace(scenario_id="test", vector_calls=1)

        violations = PolicyGuard.validate_result(spec, result)
        codes = [v.code for v in violations]
        assert "VECTOR_NOT_ALLOWED" in codes

    def test_vector_calls_with_allowance_passes(self) -> None:
        spec = ScenarioSpec(scenario_id="test", allow_vector_search=True)
        result = HandlerResult(
            scenario_id="test", reply="ok", pending_directive=PendingDirective.CLEAR,
        )
        result.resource_trace = ResourceTrace(scenario_id="test", vector_calls=1)

        violations = PolicyGuard.validate_result(spec, result)
        vector_codes = [v for v in violations if "VECTOR" in v.code]
        assert len(vector_codes) == 0


class TestPolicyGuardPending:
    """Pending 越权校验。"""

    def test_set_pending_without_allowance_triggers_violation(self) -> None:
        spec = ScenarioSpec(scenario_id="test", allow_pending=False)
        result = HandlerResult(
            scenario_id="test", reply="ok", pending_directive=PendingDirective.SET,
        )
        result.resource_trace = ResourceTrace(scenario_id="test")

        violations = PolicyGuard.validate_result(spec, result)
        codes = [v.code for v in violations]
        assert "PENDING_NOT_ALLOWED" in codes

    def test_set_pending_with_allowance_passes(self) -> None:
        spec = ScenarioSpec(scenario_id="test", allow_pending=True, risk_level="write_confirm")
        result = HandlerResult(
            scenario_id="test", reply="ok", pending_directive=PendingDirective.SET,
        )
        result.resource_trace = ResourceTrace(scenario_id="test")

        violations = PolicyGuard.validate_result(spec, result)
        pending_codes = [v for v in violations if "PENDING" in v.code]
        assert len(pending_codes) == 0

    def test_clear_pending_no_violation(self) -> None:
        spec = ScenarioSpec(scenario_id="test", allow_pending=False)
        result = HandlerResult(
            scenario_id="test", reply="ok", pending_directive=PendingDirective.CLEAR,
        )
        result.resource_trace = ResourceTrace(scenario_id="test")

        violations = PolicyGuard.validate_result(spec, result)
        pending_codes = [v for v in violations if "PENDING" in v.code]
        assert len(pending_codes) == 0


# ══════════════════════════════════════════════
# ScenarioSpec 注册表完整性
# ══════════════════════════════════════════════


class TestScenarioSpecRegistry:
    """验证所有注册的场景都有对应的 ScenarioSpec。"""

    def test_all_registered_scenarios_have_spec(self) -> None:
        """每个注册的 Handler 场景都有 ScenarioSpec 定义。"""
        from app.ai.handlers.registry import HandlerRegistry, register_default_handlers

        r = HandlerRegistry()
        register_default_handlers(r)

        missing = []
        for sid in r._handlers:
            if get_spec(sid) is None:
                missing.append(sid)

        assert not missing, f"以下场景缺少 ScenarioSpec: {missing}"

    def test_all_spec_scenarios_exist_in_registry(self) -> None:
        """每个 ScenarioSpec 对应的场景都已注册 Handler。"""
        from app.ai.handlers.registry import HandlerRegistry, register_default_handlers

        r = HandlerRegistry()
        register_default_handlers(r)

        from app.ai.scenario.spec import SCENARIO_SPECS

        missing = []
        for sid in SCENARIO_SPECS:
            if not r.has(sid):
                missing.append(sid)

        assert not missing, f"以下 ScenarioSpec 场景未注册 Handler: {missing}"


# ══════════════════════════════════════════════
# Tool functions
# ══════════════════════════════════════════════


class TestWriteSkillDetection:
    """写 Skill 检测工具函数测试。"""

    def test_write_skills_detected(self) -> None:
        assert is_write_skill("create_order_draft") is True
        assert is_write_skill("confirm_order") is True
        assert is_write_skill("remember_info") is True

    def test_read_skills_not_detected(self) -> None:
        assert is_write_skill("search_products") is False
        assert is_write_skill("get_detail") is False
        assert is_write_skill("manage_order") is False
        assert is_write_skill("recall_info") is False
