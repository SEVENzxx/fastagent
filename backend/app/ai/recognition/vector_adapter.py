"""意图样本向量召回适配器。

封装现有 VectorIntentRetriever，将召回结果转换为包含 skill 信息的 IntentCandidate。
"""

from __future__ import annotations

import logging

from app.ai.recognition.retriever import VectorIntentRetriever
from app.ai.recognition.config import DEFAULT_INTENT_CONFIG, IntentRecognitionConfig
from app.ai.recognition.types import IntentCandidate, RiskLevel, SkillName

logger = logging.getLogger(__name__)


# scenario_id 前缀 → (SkillName, RiskLevel) 映射
_SCENARIO_SKILL_MAP: dict[str, tuple[SkillName, RiskLevel]] = {
    "product.catalog": (SkillName.PRODUCT, RiskLevel.READ_ONLY),
    "product.filter_search": (SkillName.PRODUCT, RiskLevel.READ_ONLY),
    "product.semantic_recommend": (SkillName.PRODUCT, RiskLevel.READ_ONLY),
    "product.detail": (SkillName.PRODUCT, RiskLevel.READ_ONLY),
    "product.compare": (SkillName.PRODUCT, RiskLevel.READ_ONLY),
    "product.attribute_query": (SkillName.PRODUCT, RiskLevel.READ_ONLY),
    "product.pagination_sort": (SkillName.PRODUCT, RiskLevel.READ_ONLY),
    "product.sku_query": (SkillName.PRODUCT, RiskLevel.READ_ONLY),
    "order.list": (SkillName.ORDER, RiskLevel.READ_ONLY),
    "order.detail": (SkillName.ORDER, RiskLevel.READ_ONLY),
    "order.shipping_status": (SkillName.ORDER, RiskLevel.READ_ONLY),
    "order.create": (SkillName.ORDER, RiskLevel.HIGH_RISK_WRITE),
    "order.cancel": (SkillName.ORDER, RiskLevel.HIGH_RISK_WRITE),
    "order.confirm": (SkillName.ORDER, RiskLevel.HIGH_RISK_WRITE),
    "order.filter": (SkillName.ORDER, RiskLevel.READ_ONLY),
    "knowledge.policy": (SkillName.RAG, RiskLevel.READ_ONLY),
    "knowledge.qa": (SkillName.RAG, RiskLevel.READ_ONLY),
    "knowledge.product_qa": (SkillName.RAG, RiskLevel.READ_ONLY),
    "memory.save": (SkillName.MEMORY, RiskLevel.LOW_RISK_WRITE),
    "memory.recall": (SkillName.MEMORY, RiskLevel.READ_ONLY),
    "template.greeting": (SkillName.TEMPLATE, RiskLevel.READ_ONLY),
    "template.confirmation": (SkillName.TEMPLATE, RiskLevel.READ_ONLY),
    "template.farewell": (SkillName.TEMPLATE, RiskLevel.READ_ONLY),
    "human.transfer": (SkillName.HUMAN, RiskLevel.HIGH_RISK_WRITE),
}


def _resolve_skill(scenario_id: str) -> tuple[SkillName, RiskLevel]:
    """按 scenario_id 解析 SkillName 和 RiskLevel。"""
    result = _SCENARIO_SKILL_MAP.get(scenario_id)
    if result is not None:
        return result
    # 前缀兜底
    prefix = scenario_id.split(".")[0] if "." in scenario_id else ""
    prefix_map = {
        "product": (SkillName.PRODUCT, RiskLevel.READ_ONLY),
        "order": (SkillName.ORDER, RiskLevel.READ_ONLY),
        "knowledge": (SkillName.RAG, RiskLevel.READ_ONLY),
        "memory": (SkillName.MEMORY, RiskLevel.LOW_RISK_WRITE),
        "template": (SkillName.TEMPLATE, RiskLevel.READ_ONLY),
        "human": (SkillName.HUMAN, RiskLevel.HIGH_RISK_WRITE),
    }
    return prefix_map.get(prefix, (SkillName.FALLBACK, RiskLevel.READ_ONLY))


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
            if not r.scenario_id or r.scenario_id == "unknown_intent":
                continue
            skill, _risk = _resolve_skill(r.scenario_id)
            candidates.append(IntentCandidate(
                scenario_id=r.scenario_id,
                label=r.label,
                score=r.score,
                skill=skill,
                source=r.source,
                matched_text=r.matched_text,
            ))
        top5 = candidates[:5]
        logger.info(
            "意图向量召回完成：text=%s total=%d top5=%s",
            text[:40], len(candidates),
            [(c.scenario_id, round(c.score, 4)) for c in top5],
        )
        return candidates

    # _resolve_skill 已提升为模块级函数，前缀场景映射
