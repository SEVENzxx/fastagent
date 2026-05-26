"""AmbiguityDetector：歧义判断。"""

from __future__ import annotations

from app.services.ai.config.intent_config import DEFAULT_INTENT_CONFIG, IntentRecognitionConfig
from app.services.ai.intent.types import AmbiguityDecision, FusedIntent, IntentCandidate


class AmbiguityDetector:
    """根据分数和阈值判断是否高置信、歧义或低置信。"""

    def __init__(self, config: IntentRecognitionConfig | None = None) -> None:
        self.config = config or DEFAULT_INTENT_CONFIG

    def detect(self, fused: list[FusedIntent]) -> AmbiguityDecision:
        """返回歧义判断结果。"""
        if not fused:
            return AmbiguityDecision(
                intent="unknown_intent",
                label=self.config.label_for("unknown_intent"),
                confidence=0.0,
                ambiguous=False,
                need_llm=False,
                need_clarification=True,
                reason="没有候选意图",
                candidates=[],
            )

        top1 = fused[0]
        top2 = fused[1] if len(fused) > 1 else None
        gap = top1.final_score - top2.final_score if top2 else 1.0
        candidates = self._to_candidates(fused)

        if top2 is not None and gap < self.config.ambiguous_gap:
            return AmbiguityDecision(
                intent=top1.intent,
                label=top1.label,
                confidence=top1.final_score,
                ambiguous=True,
                need_llm=self.config.enable_llm_fallback,
                need_clarification=False,
                reason=f"top1/top2 分差 {gap:.2f} 小于歧义阈值",
                candidates=candidates,
            )

        if top1.final_score >= self.config.high_confidence_score:
            return AmbiguityDecision(
                intent=top1.intent,
                label=top1.label,
                confidence=top1.final_score,
                ambiguous=False,
                need_llm=False,
                reason="top1 高置信且分差足够",
                candidates=candidates,
            )

        return AmbiguityDecision(
            intent=top1.intent,
            label=top1.label,
            confidence=top1.final_score,
            ambiguous=False,
            need_llm=self.config.enable_llm_fallback,
            need_clarification=not self.config.enable_llm_fallback,
            reason="低置信候选需要兜底判断",
            candidates=candidates,
        )

    def _to_candidates(self, fused: list[FusedIntent]) -> list[IntentCandidate]:
        return [
            IntentCandidate(
                intent=item.intent,
                label=item.label,
                score=item.final_score,
                source="fusion",
                matched_text=", ".join(item.matched_examples) if item.matched_examples else None,
                reason=f"best={item.best_score:.2f}, keyword={item.keyword_boost:.2f}, context={item.context_boost:.2f}",
            )
            for item in fused
        ]
