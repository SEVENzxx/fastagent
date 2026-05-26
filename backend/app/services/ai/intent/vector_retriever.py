"""VectorIntentRetriever：向量候选召回。"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable, Sequence
from difflib import SequenceMatcher

from app.config import settings
from app.integrations.embedding_client import EmbeddingClient, EmbeddingClientError
from app.services.ai.config.intent_config import DEFAULT_INTENT_CONFIG, IntentRecognitionConfig
from app.services.ai.config.intent_examples import DEFAULT_INTENT_EXAMPLES, IntentExample
from app.services.ai.intent.types import IntentCandidate


VectorProvider = Callable[[str, int, float], Awaitable[Sequence[IntentCandidate]]]


class VectorIntentRetriever:
    """只负责召回候选意图，不直接决定最终 intent。"""

    def __init__(
        self,
        config: IntentRecognitionConfig | None = None,
        examples: Sequence[IntentExample] | None = None,
        provider: VectorProvider | None = None,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self.config = config or DEFAULT_INTENT_CONFIG
        self.examples = tuple(examples or DEFAULT_INTENT_EXAMPLES)
        self.provider = provider
        self.embedding_client = embedding_client if embedding_client is not None else (
            EmbeddingClient() if settings.AI_EMBEDDING_ENABLED else None
        )
        self._example_embeddings: list[list[float]] | None = None

    async def retrieve(self, segment: str) -> list[IntentCandidate]:
        """返回 top_k 且不低于 min_score 的候选列表。"""
        if self.provider is not None:
            provided = await self.provider(segment, self.config.vector_top_k, self.config.vector_min_score)
            return self._filter_candidates(list(provided or []))

        if self.embedding_client is not None:
            try:
                return await self._retrieve_by_embedding(segment)
            except EmbeddingClientError:
                # Embedding 服务异常不能阻断客服主链路，降级到本地轻量相似度。
                pass

        return self._retrieve_by_text_similarity(segment)

    async def _retrieve_by_embedding(self, segment: str) -> list[IntentCandidate]:
        query_embedding = await self.embedding_client.embed(segment)
        example_embeddings = await self._get_example_embeddings()
        candidates = [
            IntentCandidate(
                intent=example.intent,
                label=example.label,
                score=self._cosine_similarity(query_embedding, example_embedding),
                source="embedding",
                matched_text=example.example_text,
                reason=f"embedding 召回样本: {example.example_text}",
            )
            for example, example_embedding in zip(self.examples, example_embeddings, strict=False)
        ]
        return self._filter_candidates(candidates)

    async def _get_example_embeddings(self) -> list[list[float]]:
        if self._example_embeddings is None:
            self._example_embeddings = await self.embedding_client.embed_many(
                [example.example_text for example in self.examples]
            )
        return self._example_embeddings

    def _retrieve_by_text_similarity(self, segment: str) -> list[IntentCandidate]:
        candidates = [
            IntentCandidate(
                intent=example.intent,
                label=example.label,
                score=self._similarity(segment, example.example_text),
                source="vector_retriever",
                matched_text=example.example_text,
                reason=f"召回样本: {example.example_text}",
            )
            for example in self.examples
        ]
        return self._filter_candidates(candidates)

    def _filter_candidates(self, candidates: list[IntentCandidate]) -> list[IntentCandidate]:
        ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
        return [item for item in ranked if item.score >= self.config.vector_min_score][: self.config.vector_top_k]

    def _similarity(self, left: str, right: str) -> float:
        """开发期轻量相似度，真实生产由 embedding/pgvector 替换。"""
        left_text = left.lower().strip()
        right_text = right.lower().strip()
        if not left_text or not right_text:
            return 0.0
        if left_text == right_text:
            return 0.98
        if left_text in right_text or right_text in left_text:
            return 0.9
        return round(SequenceMatcher(None, left_text, right_text).ratio(), 4)

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right, strict=False))
        left_norm = math.sqrt(sum(item * item for item in left))
        right_norm = math.sqrt(sum(item * item for item in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return round(max(0.0, min(1.0, dot / (left_norm * right_norm))), 4)
