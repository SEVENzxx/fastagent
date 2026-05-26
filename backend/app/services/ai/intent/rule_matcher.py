"""RuleMatcher：强规则匹配。"""

from __future__ import annotations

from app.services.ai.config.intent_config import DEFAULT_INTENT_CONFIG, IntentRecognitionConfig
from app.services.ai.intent.types import IntentCandidate, IntentHit


class RuleMatcher:
    """处理明确、固定、高风险的强规则。"""

    def __init__(self, config: IntentRecognitionConfig | None = None) -> None:
        self.config = config or DEFAULT_INTENT_CONFIG

    def match(self, normalized_text: str) -> IntentHit | None:
        """命中强规则时返回 IntentHit；未命中返回 None。"""
        text = normalized_text.lower()
        if not text:
            route = self.config.route_for("silent_empty")
            return IntentHit(
                segment=normalized_text,
                intent="silent_empty",
                label="空消息",
                confidence=1.0,
                route=route.route,
                skill=route.skill,
                candidates=[],
                ambiguous=False,
                reason="空消息直接静默",
            )

        for rule in self.config.rules:
            if any(keyword.lower() in text for keyword in rule.keywords):
                candidate = IntentCandidate(
                    intent=rule.intent,
                    label=rule.label,
                    score=rule.confidence,
                    source="rule_matcher",
                    matched_text=normalized_text,
                    reason=rule.reason,
                )
                return IntentHit(
                    segment=normalized_text,
                    intent=rule.intent,
                    label=rule.label,
                    confidence=rule.confidence,
                    route=rule.route,
                    skill=rule.skill,
                    candidates=[candidate],
                    ambiguous=False,
                    reason=rule.reason or "命中强规则",
                )
        return None
