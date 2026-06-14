"""意图样本向量召回适配器。

封装现有 VectorIntentRetriever，将召回结果转换为包含 skill 信息的 IntentCandidate。
"""

from __future__ import annotations

import logging

from app.ai.recognition.retriever import VectorIntentRetriever
from app.ai.recognition.config import DEFAULT_INTENT_CONFIG, IntentRecognitionConfig
from app.ai.recognition.types import IntentCandidate, RiskLevel, SkillName

logger = logging.getLogger(__name__)


class IntentVectorAdapter:
    """向量召回适配器：召回候选意图并附加 skill / risk_level 信息。

    内部使用现有 VectorIntentRetriever，外部返回带有完整 skill 信息的候选列表。
    """

    def __init__(
        self,
        config: IntentRecognitionConfig | None = None,
    ) -> None:
        self._config = config or DEFAULT_INTENT_CONFIG
        self._retriever = VectorIntentRetriever(self._config)

    async def retrieve(
        self, text: str, *, tenant_id: int = 0,
    ) -> list[IntentCandidate]:
        """向量召回候选意图，并附加 skill 和 risk_level。

        Args:
            text: 用户消息原文（已归一化）
            tenant_id: 租户 ID，0 表示平台共享样本
        """
        raw = await self._retriever.retrieve(text, tenant_id=tenant_id)
        candidates: list[IntentCandidate] = []
        for r in raw:
            skill, risk = self._resolve_skill(r.intent)
            if not r.intent or r.intent == "unknown_intent":
                continue
            candidates.append(IntentCandidate(
                intent=r.intent,
                label=r.label,
                score=r.score,
                skill=skill,
                source=r.source,
                matched_text=r.matched_text,
            ))
        logger.info(
            "意图向量召回完成：text=%s candidates=%s skills=%s",
            text[:40], len(candidates),
            [c.skill.value for c in candidates[:5]],
        )
        return candidates

    def _resolve_skill(self, intent: str) -> tuple[SkillName, RiskLevel]:
        """按 intent 解析 skill 和 risk_level，兜底为 FALLBACK。"""
        try:
            return self._config.skill_for(intent)
        except (KeyError, AttributeError):
            return SkillName.FALLBACK, RiskLevel.READ_ONLY
