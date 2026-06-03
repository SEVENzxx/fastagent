"""IntentFusionScorer — 向量召回 + 关键词加权 + 上下文加权，三源融合打分。"""

from __future__ import annotations

from collections import defaultdict

from app.ai.classifier.intent_config import DEFAULT_INTENT_CONFIG, IntentRecognitionConfig
from app.ai.classifier.types import IntentCandidate, KeywordEntityResult

# 上下文加权规则 — 当 full_text（整条用户消息）同时包含指定关键词时，给对应 intent 加分。
# 例如：用户说"我的订单怎么还不发货"，full_text 里同时有"发货"和"订单"，
# delivery_time 额外 +0.04；"订单"也命中 order_status +0.03。
# 格式：{intent: [(需要同时出现的关键词列表, 加分值), ...]}
_DEFAULT_CONTEXT_BOOST_RULES: dict[str, list[tuple[list[str], float]]] = {
    "delivery_time": [(["发货", "订单"], 0.04), (["物流", "订单"], 0.03)],
    "order_status": [(["订单"], 0.03)],
    "logistics_status": [(["快递", "订单"], 0.04), (["物流", "订单"], 0.04)],
    "invoice": [(["发票", "订单"], 0.04)],
    "return_refund": [(["退款", "订单"], 0.04), (["退货", "订单"], 0.04)],
}


class IntentFusionScorer:
    """三源融合打分器。

    输入:
      - candidates: 向量召回的候选意图（含 Qdrant score）
      - signals: 关键词/实体提取结果（含 intent_boosts）
      - full_text: 用户完整消息（用于上下文加权）

    输出:
      - 按 final_score 降序的候选列表，每个候选分数 = min(vector_score + keyword_boost + context_boost, 1.0)
    """

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
        """融合三源分数，按 final_score 降序返回。

        1. 按 intent 分组 — 同 intent 的多个向量候选合并
        2. 补充 keyword-only 候选 — 纯关键词命中但向量未召回的 intent
        3. 逐 intent 融合 — best_score + keyword_boost + context_boost，上限 1.0
        """
        # ── 1: 按 intent 分组 ──
        grouped: dict[str, list[IntentCandidate]] = defaultdict(list)
        for candidate in candidates:
            grouped[candidate.intent].append(candidate)

        # ── 2: keyword-only 候选 — 向量没召回但关键词命中了 ──
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

        # ── 3: 逐个 intent 融合三源分数 ──
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
                    reason=f"向量{best_score:.2f}+关键词{keyword_boost:.2f}+上下文{context_boost:.2f}={final_score:.2f} | {len(items)}个候选",
                )
            )

        return sorted(fused, key=lambda item: item.score, reverse=True)

    def _context_boost(self, intent: str, segment: str, full_text: str) -> float:
        """查规则表 → full_text 里是否同时包含该 intent 的所有上下文关键词。"""
        rules = self.context_boost_rules.get(intent, [])
        for keywords, boost in rules:
            if all(kw in full_text for kw in keywords):
                return boost
        return 0.0
