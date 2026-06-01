"""批量 embedding 辅助工具。

Qdrant 写入统一交给 VectorSearchService 处理；这里仅为测试或工具类调用方
提供原始向量生成能力。
"""

from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.integrations.embedding_client import EmbeddingClient, EmbeddingClientError

logger = logging.getLogger(__name__)


class BatchEmbedder:
    """批量文本向量化。

    复用已有的 EmbeddingClient，按 batch_size 分批请求，
    失败重试 3 次（指数退避），支持零向量占位模式。
    """

    def __init__(self) -> None:
        self.client = EmbeddingClient()
        self.batch_size = settings.AI_KNOWLEDGE_BATCH_SIZE
        self.enabled = settings.AI_EMBEDDING_ENABLED

    async def embed_chunks(self, contents: list[str]) -> list[list[float] | None]:
        """批量向量化分块文本，返回与 contents 等长的向量列表。

        单条失败标记为 None，不阻塞整批。
        """
        if not contents:
            return []

        if not self.enabled:
            logger.info("Embedding 已禁用，返回零向量占位")
            return [None] * len(contents)

        results: list[list[float] | None] = [None] * len(contents)
        for offset in range(0, len(contents), self.batch_size):
            batch = contents[offset : offset + self.batch_size]
            batch_results = await self._embed_batch_with_retry(batch)

            for i in range(len(batch)):
                idx = offset + i
                if i < len(batch_results):
                    results[idx] = batch_results[i]
                else:
                    results[idx] = None

        success_count = sum(1 for r in results if r is not None)
        logger.info(
            "批量向量化完成: total=%d success=%d failed=%d",
            len(contents),
            success_count,
            len(contents) - success_count,
        )
        return results

    async def embed_single(self, text: str) -> list[float] | None:
        """单条文本向量化，失败返回 None。"""
        results = await self.embed_chunks([text])
        return results[0] if results else None

    async def _embed_batch_with_retry(
        self, texts: list[str], max_retries: int = 3
    ) -> list[list[float]]:
        """带指数退避重试的批量请求。"""
        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                return await self.client.embed_many(texts)
            except (EmbeddingClientError, OSError) as exc:
                last_error = exc
                if attempt < max_retries - 1:
                    delay = 2**attempt
                    logger.warning(
                        "Embedding 请求失败 (attempt=%d/%d)，%ds 后重试: %s",
                        attempt + 1,
                        max_retries,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)

        logger.error("Embedding 批量请求最终失败: %s", last_error)
        return []
