"""ContextStateResolver：对话状态与槽位补全。"""

from __future__ import annotations

import re

from app.ai.classifier.intent_config import DEFAULT_INTENT_CONFIG, IntentRecognitionConfig
from app.ai.classifier.types import IntentCandidate, IntentHit, KeywordEntityResult, PendingIntentState


BARE_ORDER_NO_PATTERN = re.compile(r"^[A-Za-z0-9\-]{8,32}$")

PENDING_INTERRUPT_KEYWORDS = (
    "优惠活动", "促销活动", "有什么优惠", "有优惠吗", "优惠券", "满减", "满赠",
    "支付方式", "怎么支付", "如何支付", "付款方式", "怎么付款", "如何付款",
    "支付有哪些", "支付有", "支持什么支付", "支持哪些支付",
    "你在说什么", "什么意思", "没听懂", "不明白", "算了", "取消",
)

GENERIC_QUESTION_KEYWORDS = ("什么", "哪些", "怎么", "如何", "有没有", "为啥", "为什么", "?")

PENDING_CONTINUE_KEYWORDS = (
    "下单", "买", "要", "来", "订", "拍", "就要", "就下", "这个", "这款",
    "瓶", "箱", "件", "个", "斤", "袋", "盒",
)


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

        if self._should_interrupt_pending(normalized_text):
            return None

        if (
            pending_state.skill in {"create_order", "update_price_strategy"}
            and "arguments" in pending_state.filled_entities
        ):
            filled = {"arguments": normalized_text}
            route = self.config.route_for(pending_state.intent)
            label = self.config.label_for(pending_state.intent)
            candidate = IntentCandidate(
                intent=pending_state.intent,
                label=label,
                score=0.99,
                source="context_state",
                matched_text=normalized_text,
                reason="pending skill arguments",
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
                reason=f"pending skill arguments: {filled['arguments']}",
            )

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

    def _should_interrupt_pending(self, normalized_text: str) -> bool:
        text = normalized_text.strip()
        if not text:
            return False
        if any(keyword in text for keyword in PENDING_INTERRUPT_KEYWORDS):
            return True
        if any(keyword in text for keyword in GENERIC_QUESTION_KEYWORDS):
            return not any(keyword in text for keyword in PENDING_CONTINUE_KEYWORDS)
        return False
