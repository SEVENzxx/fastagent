"""AmbiguityDetector — 基于分数与分差判断是否歧义 / 需 LLM 精判 / 需追问澄清。"""

from __future__ import annotations

from app.services.ai.config.intent_config import DEFAULT_INTENT_CONFIG, IntentRecognitionConfig
from app.services.ai.intent.types import IntentCandidate


class AmbiguityDetector:
    """根据 top1/top2 分数差和阈值，输出 (top, is_ambiguous, need_llm, need_clarification, reason)。"""

    def __init__(self, config: IntentRecognitionConfig | None = None) -> None:
        self.config = config or DEFAULT_INTENT_CONFIG

    def detect(
        self, candidates: list[IntentCandidate]
    ) -> tuple[IntentCandidate, bool, bool, bool, str]:
        if not candidates:
            return (
                IntentCandidate(intent="unknown_intent", label=self.config.label_for("unknown_intent"),
                                score=0.0, source="ambiguity"),
                False, False, True, "没有候选意图",
            )

        top1 = candidates[0]
        top2 = candidates[1] if len(candidates) > 1 else None
        gap = top1.score - top2.score if top2 else 1.0

        # top1/top2 分差 < 歧义阈值 → 歧义，触发 LLM 精判
        if top2 is not None and gap < self.config.ambiguous_gap:
            return (top1, True, self.config.enable_llm_fallback, False,
                    f"top1/top2 分差 {gap:.2f} < 歧义阈值")

        # top1 分数 ≥ 高置信阈值 → 直接采纳
        if top1.score >= self.config.high_confidence_score:
            return top1, False, False, False, "高置信且分差足够"

        # 低置信 → LLM 精判 or 追问澄清
        return (top1, False, self.config.enable_llm_fallback, not self.config.enable_llm_fallback,
                "低置信候选需兜底判断")
