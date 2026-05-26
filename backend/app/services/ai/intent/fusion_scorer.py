"""IntentFusionScorer：意图融合打分。"""

from __future__ import annotations

from collections import defaultdict

from app.services.ai.config.intent_config import DEFAULT_INTENT_CONFIG, IntentRecognitionConfig
from app.services.ai.intent.types import FusedIntent, IntentCandidate, KeywordEntityResult


class IntentFusionScorer:
    """将 vector_score、keyword_boost、context_boost 融合到 intent 维度。"""

    def __init__(self, config: IntentRecognitionConfig | None = None) -> None:
        self.config = config or DEFAULT_INTENT_CONFIG

    def score(
        self,
        candidates: list[IntentCandidate],
        signals: KeywordEntityResult,
        *,
        segment: str,
        full_text: str,
    ) -> list[FusedIntent]:
        """按 intent 聚合候选并融合分数。"""
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

        fused: list[FusedIntent] = []
        for intent, items in grouped.items():
            best_score = max(item.score for item in items)
            keyword_boost = signals.intent_boosts.get(intent, 0.0)
            context_boost = self._context_boost(intent, segment, full_text)
            final_score = min(best_score + keyword_boost + context_boost, 1.0)
            matched_examples = [item.matched_text for item in items if item.matched_text]
            fused.append(
                FusedIntent(
                    intent=intent,
                    label=self.config.label_for(intent),
                    final_score=final_score,
                    best_score=best_score,
                    hit_count=len(items),
                    matched_examples=matched_examples,
                    candidates=items,
                    keyword_boost=keyword_boost,
                    context_boost=context_boost,
                )
            )

        return sorted(fused, key=lambda item: item.final_score, reverse=True)

    def _context_boost(self, intent: str, segment: str, full_text: str) -> float:
        """上下文加权先保持保守，只处理明显多问题上下文。"""
        if intent == "delivery_time" and "发货" in full_text and "订单" in full_text:
            return 0.04
        if intent == "order_status" and "订单" in full_text:
            return 0.03
        return 0.0
