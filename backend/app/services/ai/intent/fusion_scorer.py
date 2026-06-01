"""IntentFusionScorer：意图融合打分。"""

from __future__ import annotations

from collections import defaultdict

from app.services.ai.config.intent_config import DEFAULT_INTENT_CONFIG, IntentRecognitionConfig
from app.services.ai.intent.types import IntentCandidate, KeywordEntityResult

# 上下文加权规则（平台级通用默认，租户级可通过 DB 覆盖）
# 格式：{intent: [(keywords_in_full_text, boost_value), ...]}
_DEFAULT_CONTEXT_BOOST_RULES: dict[str, list[tuple[list[str], float]]] = {
    "delivery_time": [(["发货", "订单"], 0.04)],
    "order_status": [(["订单"], 0.03)],
}


class IntentFusionScorer:
    """将 vector_score、keyword_boost、context_boost 融合到 intent 维度。"""

    def __init__(
        self,
        config: IntentRecognitionConfig | None = None,
        *,
        context_boost_rules: dict[str, list[tuple[list[str], float]]] | None = None,
    ) -> None:
        self.config = config or DEFAULT_INTENT_CONFIG
        self.context_boost_rules = context_boost_rules if context_boost_rules is not None else _DEFAULT_CONTEXT_BOOST_RULES

    def score(
        self,
        candidates: list[IntentCandidate],
        signals: KeywordEntityResult,
        *,
        segment: str,
        full_text: str,
    ) -> list[IntentCandidate]:
        """按 intent 聚合候选并融合分数，返回按融合分数降序排列的候选列表。"""
        grouped: dict[str, list[IntentCandidate]] = defaultdict(list)
        for candidate in candidates:
            grouped[candidate.intent].append(candidate)

        for intent, boost in signals.intent_boosts.items():
            if intent not in grouped:
                grouped[intent].append(
                    IntentCandidate(
                        intent=intent,
                        label=self.config.label_for(intent),
                        score=0.0,
                        source="keyword_entity",
                        matched_text=segment,
                        reason="关键词加权补充候选",
                    )
                )

        fused: list[IntentCandidate] = []
        for intent, items in grouped.items():
            best_score = max(item.score for item in items)
            keyword_boost = signals.intent_boosts.get(intent, 0.0)
            context_boost = self._context_boost(intent, segment, full_text)
            final_score = min(best_score + keyword_boost + context_boost, 1.0)
            matched_examples = [item.matched_text for item in items if item.matched_text]

            fused.append(
                IntentCandidate(
                    intent=intent,
                    label=self.config.label_for(intent),
                    score=final_score,
                    source="fusion",
                    matched_text=", ".join(matched_examples) if matched_examples else None,
                    reason=f"best={best_score:.2f} kw={keyword_boost:.2f} ctx={context_boost:.2f} hits={len(items)}",
                )
            )

        return sorted(fused, key=lambda item: item.score, reverse=True)

    def _context_boost(self, intent: str, segment: str, full_text: str) -> float:
        """基于可配置规则的上下文加权。"""
        rules = self.context_boost_rules.get(intent, [])
        for keywords, boost in rules:
            if all(kw in full_text for kw in keywords):
                return boost
        return 0.0
