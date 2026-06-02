"""VectorIntentRetriever：基于 Qdrant 的候选意图召回。

召回路径：Qdrant 向量检索 → 无结果则本地文本相似度兜底。

意图样本由 bootstrap.py 在应用启动时统一写入 Qdrant（tenant_id=0 全局共享）。
租户可通过管理后台自定义/覆盖自己的意图样本，写入时使用 tenant_id>0。
检索时按 tenant_id 过滤，租户专属样本优先，无专属样本时使用全局默认。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from difflib import SequenceMatcher

from app.services.ai.config.intent_config import DEFAULT_INTENT_CONFIG, IntentRecognitionConfig
from app.services.ai.config.intent_examples import DEFAULT_INTENT_EXAMPLES, IntentExample
from app.services.ai.intent.types import IntentCandidate
from app.services.vector_search_service import VectorDomain, VectorSearchService

logger = logging.getLogger(__name__)


class VectorIntentRetriever:
    """从 Qdrant 意图样本 collection 中召回候选意图。

    检索逻辑：
      1. 先按 tenant_id 查租户专属样本，有结果直接返回
      2. 专属样本无结果 → 查 tenant_id=0 的全局默认样本
      3. Qdrant / embedding 不可用 → 本地 SequenceMatcher 兜底

    注意：意图样本的写入不属于此类的职责，在 bootstrap.py 启动时处理。
    """

    def __init__(
        self,
        config: IntentRecognitionConfig | None = None,
        examples: Sequence[IntentExample] | None = None,
        vector_search: VectorSearchService | None = None,
    ) -> None:
        self.config = config or DEFAULT_INTENT_CONFIG
        self.examples = tuple(examples or DEFAULT_INTENT_EXAMPLES)
        self.vector_search = vector_search or VectorSearchService()

    async def retrieve(self, segment: str, *, tenant_id: int = 0) -> list[IntentCandidate]:
        """返回分数达到阈值的 top-k 候选意图。

        1. 查租户专属样本 (tenant_id)
        2. 无结果 → 查全局默认样本 (tenant_id=0)
        3. Qdrant / embedding 不可用 → 本地文本相似度兜底
        """
        # ── 1: Qdrant 向量检索（租户专属优先，全局默认兜底）──
        candidates = await self._search_qdrant(segment, tenant_id=tenant_id)
        if not candidates and tenant_id != 0:
            candidates = await self._search_qdrant(segment, tenant_id=0)

        if candidates:
            return candidates

        # ── 2: Qdrant / embedding 不可用 → 本地文本相似度兜底 ──
        fallback = self._retrieve_by_text_similarity(segment)
        logger.info("意图召回降级：Qdrant 不可用，使用本地兜底。query=%s candidates=%s", segment[:40], len(fallback))
        return fallback

    async def _search_qdrant(self, segment: str, *, tenant_id: int) -> list[IntentCandidate]:
        """对指定 tenant_id 执行 Qdrant 向量检索。"""
        hits = await self.vector_search.search_text(
            domain=VectorDomain.INTENT_SAMPLE,
            tenant_id=tenant_id,
            query=segment,
            top_k=self.config.vector_top_k,
            min_score=self.config.vector_min_score,
        )
        return [
            IntentCandidate(
                intent=str(hit.payload.get("intent") or ""),
                label=str(hit.payload.get("label") or ""),
                score=hit.score,
                source="qdrant",
                matched_text=str(hit.payload.get("example_text") or hit.payload.get("text") or ""),
                reason=f"Qdrant 意图样本: {hit.payload.get('example_text') or hit.payload.get('text')}",
            )
            for hit in hits
            if hit.payload.get("intent")
        ]

    def _retrieve_by_text_similarity(self, segment: str) -> list[IntentCandidate]:
        """Qdrant / embedding 不可用时的本地兜底召回。"""
        candidates = [
            IntentCandidate(
                intent=example.intent,
                label=example.label,
                score=self._similarity(segment, example.example_text),
                source="text_fallback",
                matched_text=example.example_text,
                reason=f"兜底意图样本: {example.example_text}",
            )
            for example in self.examples
        ]
        return self._filter_candidates(candidates)

    def _filter_candidates(self, candidates: list[IntentCandidate]) -> list[IntentCandidate]:
        """按分数降序 → 卡 min_score 阈值 → 取 top_k。"""
        ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
        return [item for item in ranked if item.score >= self.config.vector_min_score][: self.config.vector_top_k]

    def _similarity(self, left: str, right: str) -> float:
        """本地文本相似度（SequenceMatcher），兜底用的精确/包含/模糊匹配。"""
        left_text = left.lower().strip()
        right_text = right.lower().strip()
        if not left_text or not right_text:
            return 0.0
        if left_text == right_text:
            return 0.98
        if left_text in right_text or right_text in left_text:
            return 0.9
        return round(SequenceMatcher(None, left_text, right_text).ratio(), 4)
