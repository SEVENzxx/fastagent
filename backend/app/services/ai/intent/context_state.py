"""ContextStateResolver：对话状态与槽位补全。"""

from __future__ import annotations

import re

from app.services.ai.config.intent_config import DEFAULT_INTENT_CONFIG, IntentRecognitionConfig
from app.services.ai.intent.types import IntentCandidate, IntentHit, KeywordEntityResult, PendingIntentState


BARE_ORDER_NO_PATTERN = re.compile(r"^[A-Za-z0-9\-]{8,32}$")


class ContextStateResolver:
    """优先处理上一轮正在等待的槽位。

    客服里常见流程：
    用户：我要查订单
    AI：请提供订单号
    用户：202605260001

    第二轮的纯订单号不是新 intent，而是 order_status 的 order_no 槽位补全。
    """

    def __init__(self, config: IntentRecognitionConfig | None = None) -> None:
        self.config = config or DEFAULT_INTENT_CONFIG

    def resolve(
        self,
        normalized_text: str,
        signals: KeywordEntityResult,
        pending_state: PendingIntentState | None,
    ) -> IntentHit | None:
        """如果当前输入能补全 pending slot，直接返回对应 IntentHit。"""
        if pending_state is None:
            return None

        missing = [
            name
            for name in pending_state.required_entities
            if name not in pending_state.filled_entities
        ]
        if not missing:
            return None

        filled = self._extract_pending_entity(normalized_text, signals, missing)
        if not filled:
            return None

        # 只补了部分槽位时不算完成，让流水线继续处理（pending state 保持不变，
        # 下一轮用户补充剩余槽位时仍能被 context_state 命中）。
        if len(filled) < len(missing):
            return None

        route = self.config.route_for(pending_state.intent)
        label = self.config.label_for(pending_state.intent)
        matched_text = ", ".join(f"{key}={value}" for key, value in filled.items())
        candidate = IntentCandidate(
            intent=pending_state.intent,
            label=label,
            score=0.99,
            source="context_state",
            matched_text=matched_text,
            reason="命中会话 pending intent，完成槽位补全",
        )
        return IntentHit(
            segment=normalized_text,
            intent=pending_state.intent,
            label=label,
            confidence=0.99,
            route=route.route,
            skill=route.skill or pending_state.skill,
            candidates=[candidate],
            ambiguous=False,
            reason=f"补全上一轮等待槽位: {matched_text}",
        )

    def _extract_pending_entity(
        self,
        normalized_text: str,
        signals: KeywordEntityResult,
        missing: list[str],
    ) -> dict[str, str]:
        result: dict[str, str] = {}

        for entity_name in missing:
            existing = signals.entities.get(entity_name)
            if existing:
                result[entity_name] = existing[0]
                continue

            # 只有在 pending 明确等待 order_no 时，才允许裸数字/字母数字串作为订单号。
            # 无上下文时不这样做，避免把金额、验证码、手机号误判为订单号。
            if entity_name == "order_no" and BARE_ORDER_NO_PATTERN.fullmatch(normalized_text):
                result[entity_name] = normalized_text

        return result
