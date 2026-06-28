"""ScenarioTestBuilder — 架构约束测试构建器。

简化 AssistantService.process_message() 测试的 Builder 模式：
链式编排输入、期望、执行和断言。

使用示例::

    result = await (ScenarioTestBuilder(service, mocks)
        .user_says("你们有什么产品")
        .scenario_is("product.catalog")
        .expect_llm_calls(0)
        .expect_pending_directive(PendingDirective.CLEAR)
        .run())
"""

from __future__ import annotations

from typing import Any

from app.ai.assistant.result import AssistantRuntimeResult
from app.ai.context.pending_state import PendingAction, PendingDirective, PendingState
from app.ai.context.session_context import SessionContext
from app.ai.recognition.types import ScenarioDecision

# 写操作 Skill 名称集合（用于 expect_no_write_skills 断言）
_WRITE_SKILL_NAMES: frozenset[str] = frozenset({
    "create_order_draft",
    "confirm_order",
    "cancel_order",
    "save_order_address",
    "update_order_items",
})


class ScenarioTestBuilder:
    """场景测试构建器。

    Attributes:
        _service: AssistantService 实例
        _mocks: mock 依赖字典
        _text: 用户输入文本
        _scenario_id: recognition 返回的场景 ID
        _entities: ScenarioDecision 中的实体
        _pending: PendingState（None 表示无 pending）
        _pending_action: PendingGuard 返回的动作
        _context_updates: SessionContext 初始字段
        _expectations: 期望断言配置
    """

    def __init__(self, service: Any, mocks: dict[str, Any]) -> None:
        self._service = service
        self._mocks = mocks
        self._text = ""
        self._scenario_id = ""
        self._entities: dict[str, Any] = {}
        self._pending: PendingState | None = None
        self._pending_action: PendingAction = PendingAction.RESUME
        self._context_updates: dict[str, Any] = {}
        self._expectations: dict[str, Any] = {}

    # ── Arrange ────────────────────────────────

    def user_says(self, text: str) -> ScenarioTestBuilder:
        """设置用户输入文本。"""
        self._text = text
        return self

    def scenario_is(self, scenario_id: str, **entities: Any) -> ScenarioTestBuilder:
        """配置 recognition mock 返回指定的 ScenarioDecision。"""
        self._scenario_id = scenario_id
        self._entities = entities
        return self

    def with_pending(
        self,
        scenario_id: str,
        step: str = "choose_product_candidate",
        *,
        guard_action: PendingAction = PendingAction.RESUME,
        **data: Any,
    ) -> ScenarioTestBuilder:
        """配置 Pending 状态。

        Args:
            scenario_id: 场景 ID
            step: 当前步骤
            guard_action: PendingGuard 返回的动作（默认 RESUME）
            data: 兼容旧测试的占位参数，PendingState 不再保存这些字段
        """
        _ = data
        self._pending = PendingState(
            scenario_id=scenario_id,
            step=step,
            graph_thread_id="test-graph-thread",
        )
        self._pending_action = guard_action
        return self

    def with_context(self, **updates: Any) -> ScenarioTestBuilder:
        """配置 SessionContext 初始字段。"""
        self._context_updates = updates
        return self

    # ── Assert expectations ────────────────────

    def expect_reply_contains(self, *texts: str) -> ScenarioTestBuilder:
        """期望回复包含所有指定文本。"""
        self._expectations.setdefault("reply_contains", []).extend(texts)
        return self

    def expect_pending_directive(self, directive: PendingDirective) -> ScenarioTestBuilder:
        """期望 pending_directive 值。"""
        self._expectations["pending_directive"] = directive
        return self

    def expect_llm_calls(self, n: int) -> ScenarioTestBuilder:
        """期望 resource_trace.llm_calls 精确值。"""
        self._expectations["llm_calls"] = n
        return self

    def expect_vector_calls(self, n: int) -> ScenarioTestBuilder:
        """期望 resource_trace.vector_calls 精确值。"""
        self._expectations["vector_calls"] = n
        return self

    def expect_skill_calls(self, *names: str) -> ScenarioTestBuilder:
        """期望 resource_trace.skill_calls 包含指定名称。"""
        self._expectations.setdefault("skill_calls", []).extend(names)
        return self

    def expect_no_write_skills(self) -> ScenarioTestBuilder:
        """期望不调用写操作 Skill。"""
        self._expectations["no_write_skills"] = True
        return self

    # ── Act ────────────────────────────────────

    async def run(
        self,
        tenant_id: int = 1,
        conversation_id: int = 1,
    ) -> AssistantRuntimeResult:
        """编排 mock、执行 process_message、断言期望。"""
        self._setup_mocks(tenant_id, conversation_id)
        result = await self._service.process_message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            text=self._text,
        )
        self._assert_expectations(result)
        return result

    def _setup_mocks(self, tenant_id: int, conversation_id: int) -> None:
        """配置 mock 对象。"""
        mocks = self._mocks

        # 配置 SessionContext
        if self._context_updates:
            ctx = SessionContext(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                **self._context_updates,
            )
            mocks["session_store"].get.return_value = ctx

        # 配置 Pending
        mocks["pending_service"].get.return_value = self._pending
        if self._pending is not None:
            mocks["pending_guard"].check.return_value = self._pending_action

        # 配置 Recognition
        if self._scenario_id:
            entities = {"raw_text": self._text, **self._entities}
            mocks["recognition"].recognize.return_value = ScenarioDecision(
                scenario_id=self._scenario_id,
                confidence=0.9,
                entities=entities,
            )

    def _assert_expectations(self, result: AssistantRuntimeResult) -> None:
        """断言期望。"""
        metadata = result.metadata
        trace = metadata.get("resource_trace", {})

        for key, expected in self._expectations.items():
            if key == "reply_contains":
                for text in expected:
                    assert text in result.reply, (
                        f"回复应包含「{text}」，实际: {result.reply}"
                    )
            elif key == "pending_directive":
                actual = metadata.get("pending_directive")
                assert actual == expected.value, (
                    f"pending_directive 应为 {expected.value}，实际 {actual}"
                )
            elif key == "llm_calls":
                actual = trace.get("llm_calls")
                assert actual == expected, (
                    f"llm_calls 应为 {expected}，实际 {actual}"
                )
            elif key == "vector_calls":
                actual = trace.get("vector_calls")
                assert actual == expected, (
                    f"vector_calls 应为 {expected}，实际 {actual}"
                )
            elif key == "skill_calls":
                actual_calls = trace.get("skill_calls", [])
                for name in expected:
                    assert name in actual_calls, (
                        f"skill_calls 应包含 {name}，实际 {actual_calls}"
                    )
            elif key == "no_write_skills":
                actual_calls = trace.get("skill_calls", [])
                for call in actual_calls:
                    assert call not in _WRITE_SKILL_NAMES, (
                        f"不应包含写操作 Skill: {call}"
                    )
