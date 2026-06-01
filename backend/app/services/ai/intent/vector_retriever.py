"""VectorIntentRetriever：基于 Qdrant 的候选意图召回。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from difflib import SequenceMatcher

from app.services.ai.config.intent_config import DEFAULT_INTENT_CONFIG, IntentRecognitionConfig
from app.services.ai.config.intent_examples import DEFAULT_INTENT_EXAMPLES, IntentExample
from app.services.ai.intent.types import IntentCandidate
from app.services.vector_search_service import VectorDomain, VectorSearchService

logger = logging.getLogger(__name__)


VectorProvider = Callable[[str, int, float], Awaitable[Sequence[IntentCandidate]]]


class VectorIntentRetriever:
    """从意图样本 Qdrant collection 中召回候选意图。"""

    _seeded = False

    def __init__(
        self,
        config: IntentRecognitionConfig | None = None,
        examples: Sequence[IntentExample] | None = None,
        provider: VectorProvider | None = None,
        vector_search: VectorSearchService | None = None,
        **_: object,
    ) -> None:
        self.config = config or DEFAULT_INTENT_CONFIG
        self.examples = tuple(examples or DEFAULT_INTENT_EXAMPLES)
        self.provider = provider
        self.vector_search = vector_search or VectorSearchService()

    async def retrieve(self, segment: str) -> list[IntentCandidate]:
        """返回分数达到阈值的 top-k 候选意图。"""
        if self.provider is not None:
            provided = await self.provider(segment, self.config.vector_top_k, self.config.vector_min_score)
            return self._filter_candidates(list(provided or []))

        await self._ensure_intent_samples_indexed()
        hits = await self.vector_search.search_text(
            domain=VectorDomain.INTENT_SAMPLE,
            tenant_id=0,
            query=segment,
            top_k=self.config.vector_top_k,
            min_score=self.config.vector_min_score,
        )
        candidates = [
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
        if candidates:
            logger.info("Intent Qdrant recall complete: segment_len=%s candidates=%s", len(segment), len(candidates))
            return self._filter_candidates(candidates)

        # 本地文本相似度只作为 Qdrant 或 embedding 服务不可用时的可靠性兜底；
        # 生产语义召回仍以 Qdrant 为准。
        fallback = self._retrieve_by_text_similarity(segment)
        logger.info("Intent recall fallback used: segment_len=%s candidates=%s", len(segment), len(fallback))
        return fallback

    async def _ensure_intent_samples_indexed(self) -> None:
        if VectorIntentRetriever._seeded:
            return
        indexed = 0
        for index, example in enumerate(self.examples):
            point_id = await self.vector_search.upsert_text(
                domain=VectorDomain.INTENT_SAMPLE,
                tenant_id=0,
                business_id=f"{example.intent}:{index}",
                text=example.example_text,
                payload={
                    "intent": example.intent,
                    "label": example.label,
                    "route": example.route,
                    "skill": example.skill,
                    "example_text": example.example_text,
                    "is_active": True,
                },
            )
            if point_id:
                indexed += 1
        VectorIntentRetriever._seeded = indexed > 0
        logger.info("Intent samples indexed in Qdrant: examples=%s indexed=%s", len(self.examples), indexed)

    def _retrieve_by_text_similarity(self, segment: str) -> list[IntentCandidate]:
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
        ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
        return [item for item in ranked if item.score >= self.config.vector_min_score][: self.config.vector_top_k]

    def _similarity(self, left: str, right: str) -> float:
        left_text = left.lower().strip()
        right_text = right.lower().strip()
        if not left_text or not right_text:
            return 0.0
        if left_text == right_text:
            return 0.98
        if left_text in right_text or right_text in left_text:
            return 0.9
        return round(SequenceMatcher(None, left_text, right_text).ratio(), 4)
