"""AssistantService — 主编排入口。

普通 async 函数，不涉及 LangGraph。
Pending 优先处理 → RecognitionPipeline → Handler 路由 → _finalize 收口。
"""

from __future__ import annotations

import logging
from typing import Any

from app.ai.assistant.pending_guard import PendingGuard
from app.ai.assistant.result import AssistantRuntimeResult
from app.ai.context.pending_state import (
    PendingAction,
    PendingDirective,
    PendingState,
    PendingStateCorruptedError,
)
from app.ai.context.pending_service import PendingService
from app.ai.handlers.base import HandlerResult
from app.ai.handlers.registry import HandlerRegistry, register_default_handlers
from app.ai.recognition.pipeline import RecognitionPipeline
from app.ai.recognition.types import ScenarioDecision
from app.ai.context.session_context import SessionContext
from app.ai.context.session_store import ConversationStateStore
from app.ai.scenario.policy_guard import PolicyGuard, PolicyViolation
from app.ai.scenario.spec import get_spec

logger = logging.getLogger(__name__)

_PENDING_UNAVAILABLE_REPLY = "当前操作状态暂时不可用，请重新发起或转人工。"


class AssistantService:
    """AI 消息主编排入口。

    流程：
      1. 加载 SessionContext（失败降级为新会话）
      2. 检查 Pending → PendingGuard 分流
      3. 无 Pending 或 NEW_INTENT → RecognitionPipeline 场景识别
      4. HandlerRegistry 路由 → Handler.execute() / handler.resume()
      5. _finalize() 收口
    """

    def __init__(
        self,
        registry: HandlerRegistry | None = None,
        pending_service: PendingService | None = None,
        pending_guard: PendingGuard | None = None,
        recognition: RecognitionPipeline | None = None,
        session_store: ConversationStateStore | None = None,
    ) -> None:
        self.registry = registry or HandlerRegistry()
        if registry is None:
            register_default_handlers(self.registry)
        self.pending_service = pending_service or PendingService()
        self.pending_guard = pending_guard or PendingGuard()
        self.recognition = recognition or RecognitionPipeline()
        self.session_store = session_store or ConversationStateStore()

    async def process_message(
        self,
        *,
        tenant_id: int,
        conversation_id: int,
        contact_id: int | None = None,
        text: str,
    ) -> AssistantRuntimeResult:
        """处理用户消息。

        Args:
            tenant_id: 租户 ID
            conversation_id: 会话 ID
            contact_id: 联系人 ID
            text: 用户消息原文

        Returns:
            AssistantRuntimeResult
        """
        logger.info(
            "【AssistantService】入口 tenant_id=%s conversation_id=%s text_len=%s",
            tenant_id, conversation_id, len(text),
        )

        # 1. 加载 SessionContext（失败降级为新会话）
        context = await self._load_context(tenant_id, conversation_id, contact_id)

        # 2. 检查 Pending
        try:
            pending = await self.pending_service.get(tenant_id, conversation_id)
        except PendingStateCorruptedError:
            logger.error(
                "Pending 数据损坏 tenant=%s conversation=%s",
                tenant_id, conversation_id,
            )
            return await self._finalize(
                HandlerResult(
                    scenario_id="template.fallback",
                    reply=_PENDING_UNAVAILABLE_REPLY,
                    pending_directive=PendingDirective.CLEAR,
                ),
                context, tenant_id, conversation_id,
            )
        except Exception as exc:
            logger.error(
                "Pending 读取失败 tenant=%s conversation=%s error=%s",
                tenant_id, conversation_id, exc,
            )
            return await self._finalize(
                HandlerResult(
                    scenario_id="template.fallback",
                    reply=_PENDING_UNAVAILABLE_REPLY,
                    pending_directive=PendingDirective.CLEAR,
                ),
                context, tenant_id, conversation_id,
            )

        if pending is not None:
            return await self._handle_pending(
                text, context, pending, tenant_id, conversation_id,
            )

        # 3. 无 Pending → 场景识别 → Handler 执行
        return await self._recognize_and_execute(
            text, context, tenant_id, conversation_id,
        )

    # ──────────────────────────────────────
    # SessionContext 加载
    # ──────────────────────────────────────

    async def _load_context(
        self,
        tenant_id: int,
        conversation_id: int,
        contact_id: int | None,
    ) -> SessionContext:
        """加载 SessionContext，失败时降级为新会话。"""
        try:
            context = await self.session_store.get(tenant_id, conversation_id)
            context.tenant_id = tenant_id
            context.conversation_id = conversation_id
            if contact_id is not None:
                context.contact_id = contact_id
            return context
        except Exception as exc:
            logger.error(
                "SessionContext 读取失败，降级为新会话 tenant=%s conversation=%s error=%s",
                tenant_id, conversation_id, exc,
            )
            return SessionContext(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                contact_id=contact_id,
            )

    # ──────────────────────────────────────
    # Pending 处理
    # ──────────────────────────────────────

    async def _handle_pending(
        self,
        text: str,
        context: SessionContext,
        pending: PendingState,
        tenant_id: int,
        conversation_id: int,
    ) -> AssistantRuntimeResult:
        """有 Pending 时走 PendingGuard 分流。"""
        action = await self.pending_guard.check(text, context, pending)
        logger.info(
            "PendingGuard=%s scenario=%s step=%s",
            action.value, pending.scenario_id, pending.step,
        )

        if action == PendingAction.HUMAN:
            decision = ScenarioDecision(
                scenario_id="human.transfer",
                confidence=1.0,
                entities={"reason": "pending_user_request"},
            )
            handler = self.registry.get("human.transfer")
            if handler is None:
                result = HandlerResult(
                    scenario_id="human.transfer",
                    reply="正在为您转接人工客服，请稍候…",
                    pending_directive=PendingDirective.CLEAR,
                )
            else:
                context.last_user_message = text
                result = await handler.execute(decision, context)
            return await self._finalize(
                result, context, tenant_id, conversation_id,
            )

        if action == PendingAction.CANCEL:
            result = HandlerResult.cancel(
                scenario_id=pending.scenario_id,
                reply="已取消当前操作，还有什么可以帮您？",
            )
            return await self._finalize(
                result, context, tenant_id, conversation_id,
            )

        if action == PendingAction.NEW_INTENT:
            # 走 _apply_pending_with_retry 而非直调 clear，保证重试和降级
            clear_ok = await self._apply_pending_with_retry(
                HandlerResult(
                    scenario_id=pending.scenario_id,
                    reply="",
                    pending_directive=PendingDirective.CLEAR,
                ),
                tenant_id, conversation_id,
            )
            if not clear_ok:
                return await self._finalize(
                    HandlerResult(
                        scenario_id="template.fallback",
                        reply=_PENDING_UNAVAILABLE_REPLY,
                        pending_directive=PendingDirective.CLEAR,
                    ),
                    context, tenant_id, conversation_id,
                )
            return await self._recognize_and_execute(
                text, context, tenant_id, conversation_id,
            )

        # RESUME：恢复 Pending Handler
        handler = self.registry.get(pending.scenario_id)
        if handler is None:
            logger.warning(
                "未找到 Pending Handler scenario=%s，降级为兜底",
                pending.scenario_id,
            )
            result = HandlerResult(
                scenario_id=pending.scenario_id,
                reply="当前操作暂时不可用，请重新描述您的问题。",
                pending_directive=PendingDirective.CLEAR,
            )
            return await self._finalize(
                result, context, tenant_id, conversation_id,
            )

        try:
            context.last_user_message = text
            result = await handler.resume(pending, text, context)
        except NotImplementedError:
            logger.warning(
                "Handler %s 不支持 resume，降级为兜底",
                type(handler).__name__,
            )
            result = HandlerResult(
                scenario_id=pending.scenario_id,
                reply="当前操作暂时不可用，请重新描述您的问题。",
                pending_directive=PendingDirective.CLEAR,
            )
        return await self._finalize(
            result, context, tenant_id, conversation_id,
        )

    # ──────────────────────────────────────
    # 场景识别 + Handler 执行
    # ──────────────────────────────────────

    async def _recognize_and_execute(
        self,
        text: str,
        context: SessionContext,
        tenant_id: int,
        conversation_id: int,
    ) -> AssistantRuntimeResult:
        """场景识别后执行对应 Handler。"""
        # 在 Handler 执行前记录用户消息，供 handler 通过 ctx.last_user_message 读取
        context.last_user_message = text

        try:
            decision = await self.recognition.recognize(text, context)
        except Exception as exc:
            logger.error("场景识别失败: %s", exc, exc_info=True)
            decision = ScenarioDecision(
                scenario_id="template.fallback",
                confidence=0.0,
                entities={},
            )

        logger.info(
            "【场景识别】result=%s confidence=%.2f",
            decision.scenario_id, decision.confidence,
        )

        handler = self.registry.get(decision.scenario_id)
        if handler is None:
            logger.warning(
                "未找到 Handler scenario=%s，降级为 template.fallback",
                decision.scenario_id,
            )
            handler = self.registry.get("template.fallback")

        if handler is None:
            result = HandlerResult(
                scenario_id=decision.scenario_id,
                reply="抱歉，我没有理解您的意思，请重新描述一下？",
                pending_directive=PendingDirective.CLEAR,
            )
            return await self._finalize(
                result, context, tenant_id, conversation_id,
            )

        try:
            result = await handler.execute(decision, context)
        except Exception as exc:
            logger.error("Handler 执行失败: %s", exc, exc_info=True)
            result = HandlerResult(
                scenario_id=decision.scenario_id,
                reply="系统处理异常，请稍后再试。",
                pending_directive=PendingDirective.CLEAR,
            )

        return await self._finalize(
            result, context, tenant_id, conversation_id,
        )

    # ──────────────────────────────────────
    # 统一收口
    # ──────────────────────────────────────

    async def _finalize(
        self,
        result: HandlerResult,
        context: SessionContext,
        tenant_id: int,
        conversation_id: int,
    ) -> AssistantRuntimeResult:
        """主编排唯一收口点。

        1. ScenarioSpec 权限校验
        2. 应用 PendingDirective（失败重试一次）
        3. 更新并保存 SessionContext
        4. 填充 ResourceTrace
        5. 返回 AssistantRuntimeResult
        """
        # 步骤 1: ScenarioSpec 权限校验
        violations = self._validate_spec(result)

        # 步骤 2: 应用 PendingDirective（失败重试一次）
        pending_ok = await self._apply_pending_with_retry(
            result, tenant_id, conversation_id,
        )
        if not pending_ok and result.pending_directive == PendingDirective.SET:
            logger.error(
                "Pending SET 写入失败，降级回复 scenario=%s", result.scenario_id,
            )
            result.reply = "系统暂时无法保存您的操作进度，请稍后重试或转人工客服。"
            result.pending_directive = PendingDirective.CLEAR
            result.pending_state = None

        # 步骤 3: 更新并保存 SessionContext
        try:
            updated = context.apply(result.context_update)
            await self.session_store.set(tenant_id, conversation_id, updated)
        except Exception as exc:
            logger.error("SessionContext 写入失败: %s", exc)

        # 步骤 4: 填充 ResourceTrace
        result.resource_trace.pending_directive = result.pending_directive

        # 步骤 5: 组装 AssistantRuntimeResult
        final = AssistantRuntimeResult.from_handler_result(result)
        logger.info(
            "【AssistantService】完成 scenario=%s directive=%s",
            result.scenario_id, result.pending_directive.value,
        )
        return final

    def _validate_spec(self, result: HandlerResult) -> list[PolicyViolation]:
        """校验 HandlerResult 是否符合 ScenarioSpec。
        越权时记录告警并降级回复，不向用户暴露内部错误。
        """
        spec = get_spec(result.scenario_id)
        if spec is None:
            return []

        violations = PolicyGuard.validate_result(spec, result)
        for v in violations:
            logger.warning("【SpecViolation】%s", v.message)

        for v in violations:
            if v.code in ("READ_ONLY_WRITE_SKILL", "HUMAN_REQUIRED_AUTO_EXEC"):
                result.reply = "系统检测到操作异常，已自动终止。请重新描述您的问题或转人工客服。"
                result.pending_directive = PendingDirective.CLEAR
                result.pending_state = None
                break  # 只降级一次

        return violations

    async def _apply_pending_with_retry(
        self,
        result: HandlerResult,
        tenant_id: int,
        conversation_id: int,
    ) -> bool:
        """应用 PendingDirective，失败重试一次。返回是否成功。"""
        for attempt in (1, 2):
            try:
                await self.pending_service.apply_directive(
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    directive=result.pending_directive,
                    pending_state=result.pending_state,
                )
                return True
            except Exception as exc:
                logger.warning(
                    "Pending apply_directive 失败 attempt=%d/2 error=%s",
                    attempt, exc,
                )
        return False
