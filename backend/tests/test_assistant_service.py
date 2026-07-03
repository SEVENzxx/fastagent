"""AssistantService 主编排单元测试。

覆盖 5 个核心场景 + 2 个降级边界：
  1. 无 Pending 正常识别并执行 Handler
  2. Pending CANCEL 清理并 finalize
  3. Pending HUMAN 清理并转人工
  4. Pending RESUME 调用原 handler.resume
  5. _finalize 写入 pending/session/resource_trace
  6. 边界：Handler 未找到降级兜底
  7. 边界：recognition 异常降级兜底
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.ai.assistant.service import AssistantService
from app.ai.assistant.result import AssistantRuntimeResult
from app.ai.context.pending_state import (
    PendingAction,
    PendingDirective,
    PendingState,
)
from app.ai.handlers.base import HandlerResult
from app.ai.handlers.registry import HandlerRegistry, register_default_handlers
from app.ai.recognition.types import ScenarioDecision
from app.ai.context.session_context import SessionContext


# ══════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════


@pytest.fixture
def session_context() -> SessionContext:
    return SessionContext(tenant_id=1, conversation_id=1)


@pytest.fixture
def pending_state() -> PendingState:
    return PendingState(
        scenario_id="order.create",
        step="collect_missing_info",
        graph_thread_id="thread-1",
        interrupt_id="interrupt-1",
    )


@pytest.fixture
def registry() -> HandlerRegistry:
    r = HandlerRegistry()
    register_default_handlers(r)
    return r


@pytest.fixture
def service(registry: HandlerRegistry) -> AssistantService:
    """AssistantService with mocked Redis-dependent deps injected directly."""
    session_store = AsyncMock()
    session_store.get.return_value = SessionContext()
    pending_svc = AsyncMock()
    pending_svc.get.return_value = None
    return AssistantService(
        registry=registry,
        pending_service=pending_svc,
        pending_guard=AsyncMock(),
        recognition=AsyncMock(),
        session_store=session_store,
    )


@pytest.fixture
def mock_deps(service: AssistantService) -> dict:
    """返回 mock 对象引用，方便 test 内断言。"""
    return {
        "session_store": service.session_store,
        "pending_service": service.pending_service,
        "pending_guard": service.pending_guard,
        "recognition": service.recognition,
    }


# ══════════════════════════════════════════════
# 1. 无 Pending 正常流程
# ══════════════════════════════════════════════


class TestNoPending:
    """无 Pending 时走场景识别 + Handler 执行。"""

    @pytest.mark.asyncio
    async def test_greeting(self, service: AssistantService, mock_deps: dict) -> None:
        """"你好" → template.greeting → 问候回复。"""
        mock_deps["recognition"].recognize.return_value = ScenarioDecision(
            scenario_id="template.greeting", confidence=0.9,
        )
        result = await service.process_message(
            tenant_id=1, conversation_id=1, text="你好",
        )
        assert isinstance(result, AssistantRuntimeResult)
        assert result.reply == "您好！有什么可以帮您的吗？"
        assert result.metadata["scenario_id"] == "template.greeting"
        assert result.metadata["pending_directive"] == "clear"

    @pytest.mark.asyncio
    async def test_human_transfer(self, service: AssistantService, mock_deps: dict) -> None:
        """转人工 → human.transfer → 转人工回复。"""
        mock_deps["recognition"].recognize.return_value = ScenarioDecision(
            scenario_id="human.transfer", confidence=1.0,
        )
        result = await service.process_message(
            tenant_id=1, conversation_id=1, text="转人工",
        )
        assert "转接人工" in result.reply or "人工客服" in result.reply

    @pytest.mark.asyncio
    async def test_session_store_called(self, service: AssistantService, mock_deps: dict) -> None:
        """正常流程最终保存 SessionContext。"""
        mock_deps["recognition"].recognize.return_value = ScenarioDecision(
            scenario_id="template.greeting", confidence=0.9,
        )
        await service.process_message(
            tenant_id=1, conversation_id=1, text="你好",
        )
        mock_deps["session_store"].set.assert_awaited_once()
        mock_deps["pending_service"].apply_directive.assert_awaited_once()


# ══════════════════════════════════════════════
# 2. Pending CANCEL
# ══════════════════════════════════════════════


class TestPendingCancel:
    """Pending 状态下用户取消。"""

    @pytest.mark.asyncio
    async def test_cancel_clears_pending(
        self,
        service: AssistantService,
        mock_deps: dict,
        pending_state: PendingState,
    ) -> None:
        """CANCEL → 返回取消回复并清理 Pending。"""
        mock_deps["pending_service"].get.return_value = pending_state
        mock_deps["pending_guard"].check.return_value = PendingAction.CANCEL

        result = await service.process_message(
            tenant_id=1, conversation_id=1, text="算了",
        )
        assert "已取消" in result.reply
        assert result.metadata["scenario_id"] == pending_state.scenario_id
        assert result.metadata["pending_directive"] == "clear"
        # recognition 不应被调用（CANCEL 短路）
        mock_deps["recognition"].recognize.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancel_applies_clear_directive(
        self,
        service: AssistantService,
        mock_deps: dict,
        pending_state: PendingState,
    ) -> None:
        """CANCEL → apply_directive 使用 CLEAR。"""
        mock_deps["pending_service"].get.return_value = pending_state
        mock_deps["pending_guard"].check.return_value = PendingAction.CANCEL

        await service.process_message(
            tenant_id=1, conversation_id=1, text="取消",
        )
        mock_deps["pending_service"].apply_directive.assert_awaited_once()
        call_kwargs = mock_deps["pending_service"].apply_directive.call_args.kwargs
        assert call_kwargs["directive"] == PendingDirective.CLEAR


# ══════════════════════════════════════════════
# 3. Pending HUMAN
# ══════════════════════════════════════════════


class TestPendingHuman:
    """Pending 状态下用户转人工。"""

    @pytest.mark.asyncio
    async def test_human_transfer(
        self,
        service: AssistantService,
        mock_deps: dict,
        pending_state: PendingState,
    ) -> None:
        """HUMAN → 转人工回复。"""
        mock_deps["pending_service"].get.return_value = pending_state
        mock_deps["pending_guard"].check.return_value = PendingAction.HUMAN

        result = await service.process_message(
            tenant_id=1, conversation_id=1, text="转人工",
        )
        assert "转接人工" in result.reply or "人工客服" in result.reply
        assert result.metadata["scenario_id"] == "human.transfer"

    @pytest.mark.asyncio
    async def test_human_clears_pending(
        self,
        service: AssistantService,
        mock_deps: dict,
        pending_state: PendingState,
    ) -> None:
        """HUMAN → Pending 被清理。"""
        mock_deps["pending_service"].get.return_value = pending_state
        mock_deps["pending_guard"].check.return_value = PendingAction.HUMAN

        await service.process_message(
            tenant_id=1, conversation_id=1, text="转人工",
        )
        mock_deps["pending_service"].apply_directive.assert_awaited_once()
        call_kwargs = mock_deps["pending_service"].apply_directive.call_args.kwargs
        assert call_kwargs["directive"] == PendingDirective.CLEAR


# ══════════════════════════════════════════════
# 4. Pending RESUME
# ══════════════════════════════════════════════


class TestPendingResume:
    """Pending 状态下恢复 Handler 流程。"""

    @pytest.mark.asyncio
    async def test_resume_calls_handler_resume(
        self,
        service: AssistantService,
        mock_deps: dict,
        pending_state: PendingState,
    ) -> None:
        """RESUME → handler.resume 被调用。"""
        mock_deps["pending_service"].get.return_value = pending_state
        mock_deps["pending_guard"].check.return_value = PendingAction.RESUME

        with patch.object(
            service.registry.get("order.create"), "resume",
            new=AsyncMock(return_value=HandlerResult(
                scenario_id="order.create",
                reply="已恢复订单流程",
                pending_directive=PendingDirective.CLEAR,
            )),
        ) as mock_resume:
            result = await service.process_message(
                tenant_id=1, conversation_id=1, text="第一个",
            )
            mock_resume.assert_awaited_once()
            assert result.reply == "已恢复订单流程"

    @pytest.mark.asyncio
    async def test_resume_no_handler_falls_back(
        self,
        service: AssistantService,
        mock_deps: dict,
    ) -> None:
        """RESUME 但 Handler 未注册 → 降级兜底。"""
        # 使用一个未注册 scenario_id 的 Pending
        unknown_pending = PendingState(
            scenario_id="unknown.scenario",
            step="some_step",
            graph_thread_id="thread-unknown",
        )
        mock_deps["pending_service"].get.return_value = unknown_pending
        mock_deps["pending_guard"].check.return_value = PendingAction.RESUME

        result = await service.process_message(
            tenant_id=1, conversation_id=1, text="你好",
        )
        assert "暂时不可用" in result.reply
        assert result.metadata["pending_directive"] == "clear"


# ══════════════════════════════════════════════
# 5. _finalize 收口
# ══════════════════════════════════════════════


class TestFinalize:
    """验证 _finalize 写入 Pending/Session/ResourceTrace。"""

    @pytest.mark.asyncio
    async def test_finalize_applies_pending_directive(
        self,
        service: AssistantService,
        mock_deps: dict,
    ) -> None:
        """_finalize 调用 apply_directive。"""
        mock_deps["recognition"].recognize.return_value = ScenarioDecision(
            scenario_id="template.greeting", confidence=0.9,
        )
        await service.process_message(
            tenant_id=1, conversation_id=1, text="你好",
        )
        mock_deps["pending_service"].apply_directive.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_finalize_saves_session_context(
        self,
        service: AssistantService,
        mock_deps: dict,
    ) -> None:
        """_finalize 保存 SessionContext。"""
        mock_deps["recognition"].recognize.return_value = ScenarioDecision(
            scenario_id="template.greeting", confidence=0.9,
        )
        await service.process_message(
            tenant_id=1, conversation_id=1, text="你好",
        )
        mock_deps["session_store"].set.assert_awaited_once()
        # 验证传入了 SessionContext
        call_args = mock_deps["session_store"].set.call_args
        assert len(call_args[0]) == 3  # tenant_id, conversation_id, state
        assert isinstance(call_args[0][2], SessionContext)

    @pytest.mark.asyncio
    async def test_finalize_resource_trace_pending_directive(
        self,
        service: AssistantService,
        mock_deps: dict,
    ) -> None:
        """ResourceTrace 包含 pending_directive。"""
        mock_deps["recognition"].recognize.return_value = ScenarioDecision(
            scenario_id="template.greeting", confidence=0.9,
        )
        result = await service.process_message(
            tenant_id=1, conversation_id=1, text="你好",
        )
        trace = result.metadata["resource_trace"]
        assert trace["pending_directive"] == "clear"

    @pytest.mark.asyncio
    async def test_finalize_returns_assistant_result(
        self,
        service: AssistantService,
        mock_deps: dict,
    ) -> None:
        """_finalize 返回 AssistantRuntimeResult。"""
        mock_deps["recognition"].recognize.return_value = ScenarioDecision(
            scenario_id="template.greeting", confidence=0.9,
        )
        result = await service.process_message(
            tenant_id=1, conversation_id=1, text="你好",
        )
        assert isinstance(result, AssistantRuntimeResult)
        assert result.handler_result is not None
        assert result.reply == result.handler_result.reply

    @pytest.mark.asyncio
    async def test_finalize_pending_set_retry_downgrades_reply(
        self,
        service: AssistantService,
        mock_deps: dict,
    ) -> None:
        """Pending SET 写入失败重试后降级回复。"""
        from app.ai.handlers.base import BaseHandler

        # 注册一个返回 SET 的测试 Handler
        class _SetHandler(BaseHandler):
            async def execute(
                self,
                decision: object,
                context: object,
            ) -> HandlerResult:
                return HandlerResult(
                    scenario_id="test.set",
                    reply="操作已提交",
                    pending_directive=PendingDirective.SET,
                    pending_state=PendingState(
                        scenario_id="test.set",
                        step="confirm",
                        graph_thread_id="thread-set",
                    ),
                )

            async def resume(
                self,
                pending: object,
                message: str,
                context: object,
            ) -> HandlerResult:
                raise NotImplementedError

        service.registry.register("test.set", _SetHandler())
        mock_deps["recognition"].recognize.return_value = ScenarioDecision(
            scenario_id="test.set", confidence=0.9,
        )
        # apply_directive 始终失败
        mock_deps["pending_service"].apply_directive.side_effect = RuntimeError("Redis 写入失败")

        result = await service.process_message(
            tenant_id=1, conversation_id=1, text="确认",
        )
        assert "系统暂时无法保存您的操作进度" in result.reply
        assert result.metadata["pending_directive"] == "clear"
        # 验证重试了 2 次
        assert mock_deps["pending_service"].apply_directive.await_count == 2


# ══════════════════════════════════════════════
# 7. 边界：降级
# ══════════════════════════════════════════════


class TestFallback:
    """异常和缺失 Handler 的降级。"""

    @pytest.mark.asyncio
    async def test_unrecognized_scenario_falls_back(
        self,
        service: AssistantService,
        mock_deps: dict,
    ) -> None:
        """场景未注册 Handler → 降级 template.fallback。"""
        mock_deps["recognition"].recognize.return_value = ScenarioDecision(
            scenario_id="nonexistent.scenario", confidence=0.5,
        )
        result = await service.process_message(
            tenant_id=1, conversation_id=1, text="blah blah",
        )
        assert result.reply  # 有回复，不崩溃

    @pytest.mark.asyncio
    async def test_recognition_raises_falls_back(
        self,
        service: AssistantService,
        mock_deps: dict,
    ) -> None:
        """RecognitionPipeline 异常 → 降级兜底。"""
        mock_deps["recognition"].recognize.side_effect = RuntimeError("LLM 超时")
        result = await service.process_message(
            tenant_id=1, conversation_id=1, text="你好",
        )
        assert result.reply  # 有回复，不崩溃
        mock_deps["session_store"].set.assert_awaited_once()  # finalize 仍执行

    @pytest.mark.asyncio
    async def test_pending_corrupted_returns_unavailable(
        self,
        service: AssistantService,
        mock_deps: dict,
    ) -> None:
        """Pending 数据损坏 → 清理后降级为识别。"""
        from app.ai.context.pending_state import PendingStateCorruptedError

        mock_deps["pending_service"].get.side_effect = PendingStateCorruptedError("损坏")
        mock_deps["recognition"].recognize.return_value = ScenarioDecision(
            scenario_id="template.fallback", confidence=0.0,
        )

        result = await service.process_message(
            tenant_id=1, conversation_id=1, text="你好",
        )
        # 损坏数据在 _get_pending_or_none 内部清理，不走旧的全阻断路径
        assert result.reply
        mock_deps["recognition"].recognize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pending_corrupted_clear_failure_still_returns_unavailable(
        self,
        service: AssistantService,
        mock_deps: dict,
    ) -> None:
        """Pending 数据损坏 + clear 也失败 → 不抛异常，降级为识别。"""
        from app.ai.context.pending_state import PendingStateCorruptedError

        mock_deps["pending_service"].get.side_effect = PendingStateCorruptedError("损坏")
        # apply_directive 也失败
        mock_deps["pending_service"].apply_directive.side_effect = RuntimeError("Redis 写入失败")
        mock_deps["recognition"].recognize.return_value = ScenarioDecision(
            scenario_id="template.fallback", confidence=0.0,
        )

        result = await service.process_message(
            tenant_id=1, conversation_id=1, text="你好",
        )
        assert result.reply
        assert result.metadata["pending_directive"] == "clear"

    @pytest.mark.asyncio
    async def test_pending_read_raises_generic_exception(
        self,
        service: AssistantService,
        mock_deps: dict,
    ) -> None:
        """Pending 读取抛通用异常 → 降级为新识别，不阻断用户消息。"""
        mock_deps["pending_service"].get.side_effect = RuntimeError("Redis 连接超时")
        mock_deps["recognition"].recognize.return_value = ScenarioDecision(
            scenario_id="template.fallback", confidence=0.0,
        )

        result = await service.process_message(
            tenant_id=1, conversation_id=1, text="你好",
        )
        assert result.reply
        assert result.metadata["pending_directive"] == "clear"
        # 降级为识别（Transient Redis 不应阻断用户消息）
        mock_deps["recognition"].recognize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_session_context_read_failure_falls_back(
        self,
        service: AssistantService,
        mock_deps: dict,
    ) -> None:
        """SessionContext 读取失败 → 降级为新会话，继续识别。"""
        mock_deps["session_store"].get.side_effect = RuntimeError("Redis 连接超时")
        mock_deps["recognition"].recognize.return_value = ScenarioDecision(
            scenario_id="template.greeting", confidence=0.9,
        )

        result = await service.process_message(
            tenant_id=1, conversation_id=1, text="你好",
        )
        # 仍正常回复（降级为新会话）
        assert result.reply == "您好！有什么可以帮您的吗？"
        # session_store.set 应被调用（新会话被保存）
        mock_deps["session_store"].set.assert_awaited_once()


# ══════════════════════════════════════════════
# 8. Product 场景（默认 registry，不崩溃）
# ══════════════════════════════════════════════


class TestProductScenario:
    """默认 registry 跑 ProductHandler，不应返回系统异常。"""

    @pytest.mark.asyncio
    async def _make_service(self, scenario_id: str, text: str) -> AssistantService:
        registry = HandlerRegistry()
        register_default_handlers(registry)
        session_store = AsyncMock()
        session_store.get.return_value = SessionContext(tenant_id=1, conversation_id=1)
        pending_svc = AsyncMock()
        pending_svc.get.return_value = None
        recognition = AsyncMock()
        recognition.recognize.return_value = ScenarioDecision(
            scenario_id=scenario_id,
            confidence=0.9,
            entities={"raw_text": text},
        )
        return AssistantService(
            registry=registry,
            pending_service=pending_svc,
            pending_guard=AsyncMock(),
            recognition=recognition,
            session_store=session_store,
        )

    @pytest.mark.asyncio
    async def test_product_detail_with_default_registry(self) -> None:
        """默认 AssistantService + 默认 registry 跑 product.detail，不应崩溃。"""
        service = await self._make_service("product.detail", "无线耳机")
        result = await service.process_message(tenant_id=1, conversation_id=1, text="无线耳机")
        assert result.reply, "应有回复，不返回系统异常"
        assert "系统异常" not in result.reply
        assert "暂时不可用" not in result.reply

    @pytest.mark.asyncio
    async def test_catalog_with_default_registry(self) -> None:
        """product.catalog 使用默认 registry，不应返回系统异常。"""
        service = await self._make_service("product.catalog", "分类")
        result = await service.process_message(tenant_id=1, conversation_id=1, text="分类")
        assert result.reply, "应有回复，不返回系统异常"
        assert "系统异常" not in result.reply
        assert "暂时不可用" not in result.reply


# ══════════════════════════════════════════════
# 9. Order 场景（默认 registry，不崩溃）
# ══════════════════════════════════════════════


class TestOrderScenario:
    """默认 registry 跑 OrderHandler，不应返回系统异常。

    OrderHandler 依赖 OrderReferenceResolver（纯文本，无 DB），
    以及 OrderSkill.manage_order（lazy import，测试环境降级到 db=None 后返回空）。
    只要不抛异常即通过。
    """

    @pytest.mark.asyncio
    async def _make_service(self, scenario_id: str, text: str) -> AssistantService:
        registry = HandlerRegistry()
        register_default_handlers(registry)
        session_store = AsyncMock()
        session_store.get.return_value = SessionContext(
            tenant_id=1, conversation_id=1, contact_id=1,
        )
        pending_svc = AsyncMock()
        pending_svc.get.return_value = None
        recognition = AsyncMock()
        recognition.recognize.return_value = ScenarioDecision(
            scenario_id=scenario_id,
            confidence=0.9,
            entities={"raw_text": text},
        )
        return AssistantService(
            registry=registry,
            pending_service=pending_svc,
            pending_guard=AsyncMock(),
            recognition=recognition,
            session_store=session_store,
        )

    @pytest.mark.asyncio
    async def test_order_list_with_default_registry(self) -> None:
        """order.list 使用默认 registry，不应返回系统异常。"""
        service = await self._make_service("order.list", "查看我的订单")
        result = await service.process_message(tenant_id=1, conversation_id=1, text="查看我的订单")
        assert result.reply, "应有回复，不返回系统异常"
        assert "系统异常" not in result.reply
        assert "暂时不可用" not in result.reply

    @pytest.mark.asyncio
    async def test_order_detail_with_default_registry(self) -> None:
        """order.detail 使用默认 registry，不应返回系统异常。

        真实环境下，manage_order 会连接 DB 查询。测试环境 DB 不可用，
        降级后返回 ToolResult(ok=False)，Handler 返回"暂时无法查询"。
        不崩溃即可。
        """
        service = await self._make_service("order.detail", "订单号20240614001")
        result = await service.process_message(tenant_id=1, conversation_id=1, text="订单号20240614001")
        assert result.reply, "应有回复，不返回系统异常"
        assert "系统异常" not in result.reply

    @pytest.mark.asyncio
    async def test_order_shipping_with_default_registry(self) -> None:
        """order.shipping_status 使用默认 registry，不应返回系统异常。"""
        service = await self._make_service("order.shipping_status", "发货了吗")
        result = await service.process_message(tenant_id=1, conversation_id=1, text="发货了吗")
        assert result.reply, "应有回复，不返回系统异常"
        assert "系统异常" not in result.reply


# ══════════════════════════════════════════════
# 10. Knowledge 场景（默认 registry，不崩溃）
# ══════════════════════════════════════════════


class TestKnowledgeScenario:
    """默认 registry 跑 KnowledgeHandler，不应返回系统异常。

    KnowledgeHandler 依赖 KnowledgeSkill（search_qa / search_knowledge），
    测试环境 DB 不可用时降级到 db=None 后返回空 ToolResult。
    只要不抛异常即通过。
    """

    @pytest.mark.asyncio
    async def _make_service(self, scenario_id: str, text: str) -> AssistantService:
        registry = HandlerRegistry()
        register_default_handlers(registry)
        session_store = AsyncMock()
        session_store.get.return_value = SessionContext(tenant_id=1, conversation_id=1)
        pending_svc = AsyncMock()
        pending_svc.get.return_value = None
        recognition = AsyncMock()
        recognition.recognize.return_value = ScenarioDecision(
            scenario_id=scenario_id,
            confidence=0.9,
            entities={"raw_text": text},
        )
        return AssistantService(
            registry=registry,
            pending_service=pending_svc,
            pending_guard=AsyncMock(),
            recognition=recognition,
            session_store=session_store,
        )

    @pytest.mark.asyncio
    async def test_knowledge_qa_with_default_registry(self) -> None:
        """knowledge.qa 使用默认 registry，不应返回系统异常。"""
        service = await self._make_service("knowledge.qa", "有什么优惠")
        result = await service.process_message(tenant_id=1, conversation_id=1, text="有什么优惠")
        assert result.reply, "应有回复，不返回系统异常"
        assert "系统异常" not in result.reply

    @pytest.mark.asyncio
    async def test_knowledge_policy_with_default_registry(self) -> None:
        """knowledge.policy 使用默认 registry，不应返回系统异常。"""
        service = await self._make_service("knowledge.policy", "保修政策")
        result = await service.process_message(tenant_id=1, conversation_id=1, text="保修政策")
        assert result.reply, "应有回复，不返回系统异常"
        assert "系统异常" not in result.reply


class TestMemoryScenario:
    """默认 registry 跑 MemoryHandler，不应返回系统异常。

    MemoryHandler 依赖 remember_info skill（需 DB + LLM），
    测试环境 DB 不可用时降级返回空 ToolResult。
    只要不抛异常即通过。
    """

    @pytest.mark.asyncio
    async def _make_service(self, text: str) -> AssistantService:
        registry = HandlerRegistry()
        register_default_handlers(registry)
        session_store = AsyncMock()
        session_store.get.return_value = SessionContext(tenant_id=1, conversation_id=1, contact_id=1)
        pending_svc = AsyncMock()
        pending_svc.get.return_value = None
        recognition = AsyncMock()
        recognition.recognize.return_value = ScenarioDecision(
            scenario_id="memory.save",
            confidence=0.9,
            entities={"raw_text": text},
        )
        return AssistantService(
            registry=registry,
            pending_service=pending_svc,
            pending_guard=AsyncMock(),
            recognition=recognition,
            session_store=session_store,
        )

    @pytest.mark.asyncio
    async def test_memory_save_with_default_registry(self) -> None:
        """memory.save 使用默认 registry，不应返回系统异常。"""
        service = await self._make_service("我喜欢草莓味的蛋糕")
        result = await service.process_message(tenant_id=1, conversation_id=1, text="我喜欢草莓味的蛋糕")
        assert result.reply, "应有回复，不返回系统异常"
        assert "系统异常" not in result.reply


class TestTemplateScenario:
    """默认 registry 跑 TemplateHandler，不应返回系统异常。"""

    @pytest.mark.asyncio
    async def _make_service(self, scenario_id: str) -> AssistantService:
        registry = HandlerRegistry()
        register_default_handlers(registry)
        session_store = AsyncMock()
        session_store.get.return_value = SessionContext(tenant_id=1, conversation_id=1)
        pending_svc = AsyncMock()
        pending_svc.get.return_value = None
        recognition = AsyncMock()
        recognition.recognize.return_value = ScenarioDecision(
            scenario_id=scenario_id,
            confidence=1.0,
            entities={},
        )
        return AssistantService(
            registry=registry,
            pending_service=pending_svc,
            pending_guard=AsyncMock(),
            recognition=recognition,
            session_store=session_store,
        )

    @pytest.mark.asyncio
    async def test_greeting_with_default_registry(self) -> None:
        """template.greeting 使用默认 registry，不应返回系统异常。"""
        service = await self._make_service("template.greeting")
        result = await service.process_message(tenant_id=1, conversation_id=1, text="你好")
        assert result.reply, "应有回复，不返回系统异常"
        assert "系统异常" not in result.reply

    @pytest.mark.asyncio
    async def test_fallback_with_default_registry(self) -> None:
        """template.fallback 使用默认 registry，不应返回系统异常。"""
        service = await self._make_service("template.fallback")
        result = await service.process_message(tenant_id=1, conversation_id=1, text="?")
        assert result.reply, "应有回复，不返回系统异常"
        assert "系统异常" not in result.reply


class TestHumanScenario:
    """默认 registry 跑 HumanHandler，不应返回系统异常。"""

    @pytest.mark.asyncio
    async def test_transfer_with_default_registry(self) -> None:
        """human.transfer 使用默认 registry，不应返回系统异常。"""
        registry = HandlerRegistry()
        register_default_handlers(registry)
        session_store = AsyncMock()
        session_store.get.return_value = SessionContext(tenant_id=1, conversation_id=1)
        pending_svc = AsyncMock()
        pending_svc.get.return_value = None
        recognition = AsyncMock()
        recognition.recognize.return_value = ScenarioDecision(
            scenario_id="human.transfer",
            confidence=1.0,
            entities={"reason": "测试转人工"},
        )
        service = AssistantService(
            registry=registry,
            pending_service=pending_svc,
            pending_guard=AsyncMock(),
            recognition=recognition,
            session_store=session_store,
        )
        result = await service.process_message(tenant_id=1, conversation_id=1, text="转人工")
        assert result.reply, "应有回复，不返回系统异常"
        assert "系统异常" not in result.reply
        assert "转接人工客服" in result.reply
        # 断言 handoff 信号被传递
        assert result.handler_result is not None
        cu = result.handler_result.context_update
        assert cu.get("requires_human_handoff") is True
        assert "reason" in cu.get("pending_human_approval", {})
