"""意图候选的置信度判定：决定是否采纳、是否 LLM 精判、是否追问澄清。"""

from __future__ import annotations

from app.ai.classifier.intent_config import DEFAULT_INTENT_CONFIG, IntentRecognitionConfig
from app.ai.classifier.types import IntentCandidate


class AmbiguityDetector:
    """根据候选分数和分差，输出四种决策路径。

    返回值：(top, is_ambiguous, need_llm, need_clarification, reason)
      - top: 采纳的最佳候选
      - is_ambiguous: 是否歧义（需 LLM 精判）
      - need_llm: 是否需要 LLM 精判
      - need_clarification: 是否需要追问澄清
      - reason: 决策原因
    """

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

        # ── 路径 1：歧义 — top1 和 top2 分差太小，拿不准 → LLM 精判 ──
        if top2 is not None and gap < self.config.ambiguous_gap:
            return (top1, True, self.config.enable_llm_fallback, False,
                    f"top1/top2 分差 {gap:.2f} < 歧义阈值")

        # ── 路径 2：高置信 → 直接采纳（无歧义 + 分数高）──
        if top1.score >= self.config.high_confidence_score:
            return top1, False, False, False, "高置信且分差足够，直接采纳"

        # ── 路径 3：中置信 → 直接采纳，不调 LLM，由下游技能执行兜底 ──
        # 分数介于 vector_min_score 和 high_confidence_score 之间，
        # 虽然有歧义但分数差距足够大。节省 LLM 调用，交给 AGENT/GENERAL_REPLY 处理。
        if top1.score >= self.config.vector_min_score:
            return top1, False, False, False, "中置信，由下游技能执行兜底"

        # ── 路径 4：低置信 → LLM 精判或追问澄清 ──
        return (
            top1,
            False,
            self.config.enable_llm_fallback,
            not self.config.enable_llm_fallback,
            "低置信候选，需兜底判断",
        )
