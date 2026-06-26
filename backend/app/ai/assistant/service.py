"""AssistantService — 主编排入口。

核心原则：用户消息来了必须得有回复，异常不能卡消息或抛给用户。
所有降级走统一 _fallback_result()，按严重程度收敛到少量话术。

流程：
  1. 加载 SessionContext + PendingState（失败降级）
  2. 有 Pending → _handle_pending / 无 Pending → _recognize_and_execute
  3. _finalize 统一收口（权限校验 + 持久化）
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
)
from app.ai.handlers.base import HandlerResult
from app.ai.handlers.registry import HandlerRegistry, register_default_handlers
from app.ai.context.context_resolver import ContextResolver, ContextResolution
from app.ai.recognition.pipeline import RecognitionPipeline
from app.ai.recognition.types import ScenarioDecision
from app.ai.context.session_context import SessionContext
from app.ai.context.session_store import ConversationStateStore
from app.ai.scenario.policy_guard import PolicyGuard, PolicyViolation
from app.ai.scenario.spec import get_spec

logger = logging.getLogger(__name__)

_FALLBACK_REPLIES: dict[str, str] = {
    "error": "系统处理异常，请稍后再试。",
    "unavailable": "当前操作暂时不可用，请重新描述您的问题或转人工客服。",
}


class AssistantService:
    """AI 消息主编排入口。"""

    def __init__(
        self,
        registry: HandlerRegistry | None = None,
        pending_service: Any = None,
        pending_guard: PendingGuard | None = None,
        recognition: RecognitionPipeline | None = None,
        session_store: ConversationStateStore | None = None,
    ) -> None:
        self.registry = registry or HandlerRegistry()
        if registry is None:
            register_default_handlers(self.registry)
        from app.ai.context.pending_service import PendingService
        self.pending_service = pending_service or PendingService()
        self.pending_guard = pending_guard or PendingGuard()
        self.recognition = recognition or RecognitionPipeline()
        self.context_resolver = ContextResolver()
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

        1. 加载状态（失败降级）
        2. 有 Pending → resume / 无 Pending → 识别执行
        3. 统一收口
        """
        logger.info(
            "【AssistantService】入口 tenant_id=%s conversation_id=%s text_len=%s",
            tenant_id, conversation_id, len(text),
        )

        # 1. 加载状态（失败降级）
        context = await self._load_context(tenant_id, conversation_id, contact_id)
        pending = await self._get_pending_or_none(tenant_id, conversation_id)

        # 2. 主干逻辑（任何未预期异常都走统一降级）
        context.last_user_message = text
        try:
            if pending is not None:
                result = await self._handle_pending(
                    pending, text, context, tenant_id, conversation_id,
                )
            else:
                result = await self._try_context_or_recognize(text, context)
        except Exception:
            logger.error("编排执行失败", exc_info=True)
            result = self._fallback_result()

        # 3. 统一收口
        return await self._finalize(result, context, tenant_id, conversation_id)

    # ──────────────────────────────────────
    # 状态加载
    # ──────────────────────────────────────

    async def _load_context(
        self,
        tenant_id: int,
        conversation_id: int,
        contact_id: int | None,
    ) -> SessionContext:
        """加载 SessionContext，失败降级为新会话。"""
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

    async def _get_pending_or_none(
        self,
        tenant_id: int,
        conversation_id: int,
    ) -> PendingState | None:
        """加载 Pending 状态，失败返回 None（降级为新识别）。"""
        try:
            return await self.pending_service.get(tenant_id, conversation_id)
        except Exception:
            logger.error(
                "Pending 读取失败 tenant=%s conversation=%s",
                tenant_id, conversation_id, exc_info=True,
            )
            return None

    # ──────────────────────────────────────
    # Pending 处理
    # ──────────────────────────────────────

    async def _handle_pending(
        self,
        pending: PendingState,
        text: str,
        context: SessionContext,
        tenant_id: int,
        conversation_id: int,
    ) -> HandlerResult:
        """处理 Pending 流程。返回 HandlerResult（内部异常不抛到外层）。"""
        action = await self.pending_guard.check(text, context, pending, self.recognition)
        logger.info(
            "PendingGuard=%s scenario=%s step=%s",
            action.value, pending.scenario_id, pending.step,
        )

        if action == PendingAction.HUMAN:
            return await self._handle_pending_human(pending, context)

        if action == PendingAction.CANCEL:
            return HandlerResult.cancel(
                scenario_id=pending.scenario_id,
                reply="已取消当前操作，还有什么可以帮您？",
            )

        if action == PendingAction.NEW_INTENT:
            return await self._handle_pending_new_intent(
                text, context, pending, tenant_id, conversation_id,
            )

        # RESUME
        return await self._handle_pending_resume(pending, text, context)

    async def _handle_pending_human(
        self,
        pending: PendingState,
        context: SessionContext,
    ) -> HandlerResult:
        """Pending 转人工。"""
        handler = self.registry.get("human.transfer")
        if handler is None:
            return HandlerResult(
                scenario_id="human.transfer",
                reply="正在为您转接人工客服，请稍候…",
                pending_directive=PendingDirective.CLEAR,
            )
        return await handler.execute(
            ScenarioDecision(
                scenario_id="human.transfer",
                confidence=1.0,
                entities={"reason": "pending_user_request"},
            ),
            context,
        )

    async def _handle_pending_new_intent(
        self,
        text: str,
        context: SessionContext,
        pending: PendingState,
        tenant_id: int,
        conversation_id: int,
    ) -> HandlerResult:
        """清除当前 Pending 后重新走识别链路。"""
        clear_ok = await self._apply_pending_with_retry(
            HandlerResult(
                scenario_id=pending.scenario_id,
                reply="",
                pending_directive=PendingDirective.CLEAR,
            ),
            tenant_id, conversation_id,
        )
        if not clear_ok:
            return self._fallback_result(severity="unavailable")
        return await self._try_context_or_recognize(text, context)

    async def _handle_pending_resume(
        self,
        pending: PendingState,
        text: str,
        context: SessionContext,
    ) -> HandlerResult:
        """恢复 Pending Handler。"""
        handler = self.registry.get(pending.scenario_id)
        if handler is None:
            logger.warning(
                "未找到 Pending Handler scenario=%s", pending.scenario_id,
            )
            return self._fallback_result(severity="unavailable")

        try:
            return await handler.resume(pending, text, context)
        except NotImplementedError:
            logger.warning(
                "Handler %s 不支持 resume", type(handler).__name__,
            )
            return self._fallback_result(severity="unavailable")

    # ──────────────────────────────────────
    # 场景识别 + Handler 执行
    # ──────────────────────────────────────

    async def _try_context_or_recognize(
        self,
        text: str,
        context: SessionContext,
    ) -> HandlerResult:
        """上下文解析优先 → 兜底场景识别。

        ContextResolver 处理序号/指代/省略型三种上下文依赖，
        解析成功则跳过 RecognitionPipeline 直接路由 Handler。
        """
        try:
            resolution = await self.context_resolver.resolve(text, context)
        except Exception as exc:
            logger.error("ContextResolver 失败: %s", exc, exc_info=True)
            resolution = None

        if resolution is not None:
            decision = ScenarioDecision(
                scenario_id=resolution.scenario_id,
                confidence=resolution.confidence,
                entities=resolution.entities,
            )
            handler = self.registry.get(resolution.scenario_id)
            if handler is not None:
                logger.info(
                    "【ContextResolver】命中 scenario=%s product_id=%s",
                    resolution.scenario_id,
                    resolution.entities.get("product_id"),
                )
                try:
                    return await handler.execute(decision, context)
                except Exception as exc:
                    logger.error(
                        "ContextResolver Handler 执行失败 scenario=%s: %s",
                        resolution.scenario_id, exc, exc_info=True,
                    )
                    return self._fallback_result()

        return await self._recognize_and_execute(text, context)

    async def _recognize_and_execute(
        self,
        text: str,
        context: SessionContext,
    ) -> HandlerResult:
        """场景识别后执行对应 Handler。"""
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
                "未找到 Handler scenario=%s，降级为兜底",
                decision.scenario_id,
            )
            handler = self.registry.get("template.fallback")

        if handler is None:
            return self._fallback_result()

        try:
            return await handler.execute(decision, context)
        except Exception as exc:
            logger.error("Handler 执行失败: %s", exc, exc_info=True)
            return self._fallback_result()

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
        3. SessionContext 持久化（不阻断）
        4. 组装 AssistantRuntimeResult
        """
        # 1. 权限校验
        self._validate_spec(result)

        # 2. Pending 持久化（失败重试一次）
        pending_ok = await self._apply_pending_with_retry(
            result, tenant_id, conversation_id,
        )
        if not pending_ok and result.pending_directive == PendingDirective.SET:
            logger.error(
                "Pending SET 写入失败，降级 scenario=%s", result.scenario_id,
            )
            result.reply = "系统暂时无法保存您的操作进度，请稍后重试或转人工客服。"
            result.pending_directive = PendingDirective.CLEAR
            result.pending_state = None

        # 3. SessionContext 持久化（不阻断）
        try:
            updated = context.apply(result.context_update)
            await self.session_store.set(tenant_id, conversation_id, updated)
        except Exception as exc:
            logger.error("SessionContext 写入失败: %s", exc)

        # 4. 组装结果
        result.resource_trace.pending_directive = result.pending_directive

        final = AssistantRuntimeResult.from_handler_result(result)
        logger.info(
            "【AssistantService】完成 scenario=%s directive=%s",
            result.scenario_id, result.pending_directive.value,
        )
        return final

    # ──────────────────────────────────────
    # 降级与校验
    # ──────────────────────────────────────

    def _fallback_result(self, severity: str = "error") -> HandlerResult:
        """统一降级函数。按严重程度选择兜底话术。

        - "error": 系统异常，请稍后再试（Handler 执行失败等）
        - "unavailable": 操作不可用，请重新描述或转人工（Pending 损坏、Handler 缺失等）
        """
        return HandlerResult(
            scenario_id="template.fallback",
            reply=_FALLBACK_REPLIES.get(severity, _FALLBACK_REPLIES["error"]),
            pending_directive=PendingDirective.CLEAR,
        )

    def _validate_spec(self, result: HandlerResult) -> list[PolicyViolation]:
        """校验 HandlerResult 是否符合 ScenarioSpec。"""
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
                break

        return violations

    async def _apply_pending_with_retry(
        self,
        result: HandlerResult,
        tenant_id: int,
        conversation_id: int,
    ) -> bool:
        """应用 PendingDirective，失败重试一次。"""
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
