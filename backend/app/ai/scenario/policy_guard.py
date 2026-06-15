"""PolicyGuard — 场景权限校验。

在 _finalize() 中根据 ScenarioSpec 校验 HandlerResult，
越权时返回 PolicyViolation 列表，由调用方决定降级策略。
"""

from __future__ import annotations

import logging
from typing import Any

from app.ai.handlers.base import HandlerResult
from app.ai.scenario.spec import ScenarioSpec, is_write_skill
from app.ai.context.pending_state import PendingDirective

logger = logging.getLogger(__name__)


class PolicyViolation:
    """权限越权描述。"""

    def __init__(self, code: str, message: str, details: Any = None) -> None:
        self.code = code
        self.message = message
        self.details = details

    def __repr__(self) -> str:
        return f"PolicyViolation({self.code}: {self.message})"


class PolicyGuard:
    """场景策略守卫。

    在 _finalize() 中对 HandlerResult 做后置校验。
    不阻止执行，只报告越权行为。
    """

    @staticmethod
    def validate_result(
        spec: ScenarioSpec,
        result: HandlerResult,
    ) -> list[PolicyViolation]:
        """校验 HandlerResult 是否符合 ScenarioSpec。

        Args:
            spec: 场景规约
            result: Handler 执行结果

        Returns:
            越权列表（空列表表示无越权）
        """
        violations: list[PolicyViolation] = []
        trace = result.resource_trace

        # ── 1. Skill 越权校验 ──
        for skill in trace.skill_calls:
            if skill not in spec.allowed_skills:
                violations.append(PolicyViolation(
                    code="SKILL_NOT_ALLOWED",
                    message=f"场景 {spec.scenario_id} 调用了未允许的 Skill: {skill}",
                    details={"skill": skill, "allowed": list(spec.allowed_skills)},
                ))

        # ── 2. Risk level 校验 ──
        if spec.risk_level == "read_only":
            # read_only 场景不能有写 Skill 调用
            write_calls = [s for s in trace.skill_calls if is_write_skill(s)]
            if write_calls:
                violations.append(PolicyViolation(
                    code="READ_ONLY_WRITE_SKILL",
                    message=f"read_only 场景 {spec.scenario_id} 调用了写 Skill: {write_calls}",
                    details={"write_skills": write_calls},
                ))
            # read_only 不能 SET pending
            if result.pending_directive == PendingDirective.SET:
                violations.append(PolicyViolation(
                    code="READ_ONLY_SET_PENDING",
                    message=f"read_only 场景 {spec.scenario_id} 不能 SET Pending",
                    details={"pending_directive": "set"},
                ))

        elif spec.risk_level == "human_required":
            # human_required 只能转人工，不能自动处理
            if result.scenario_id != "human.transfer":
                violations.append(PolicyViolation(
                    code="HUMAN_REQUIRED_AUTO_EXEC",
                    message=f"human_required 场景 {spec.scenario_id} 非转人工路径",
                    details={"scenario_id": result.scenario_id},
                ))

        # ── 3. LLM 越权校验 ──
        if trace.llm_calls > 0 and not spec.allow_llm_entity_extraction and not spec.allow_llm_reply_generation:
            violations.append(PolicyViolation(
                code="LLM_NOT_ALLOWED",
                message=f"场景 {spec.scenario_id} 不允许 LLM 调用（实际 {trace.llm_calls} 次）",
                details={"llm_calls": trace.llm_calls},
            ))

        # ── 4. Vector 越权校验 ──
        if trace.vector_calls > 0 and not spec.allow_vector_search:
            violations.append(PolicyViolation(
                code="VECTOR_NOT_ALLOWED",
                message=f"场景 {spec.scenario_id} 不允许向量检索（实际 {trace.vector_calls} 次）",
                details={"vector_calls": trace.vector_calls},
            ))

        # ── 5. Pending 越权校验 ──
        if result.pending_directive == PendingDirective.SET and not spec.allow_pending:
            violations.append(PolicyViolation(
                code="PENDING_NOT_ALLOWED",
                message=f"场景 {spec.scenario_id} 不允许 SET Pending",
                details={"pending_directive": "set"},
            ))

        return violations
