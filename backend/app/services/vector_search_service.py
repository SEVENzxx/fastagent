"""基于 Qdrant 的统一语义索引与检索服务。"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.config import settings
from app.integrations.embedding_client import EmbeddingClient, EmbeddingClientError
from app.integrations.qdrant_client import QdrantClientError, QdrantVectorClient

logger = logging.getLogger(__name__)


class VectorDomain(StrEnum):
    INTENT_SAMPLE = "intent_sample"
    KNOWLEDGE_CHUNK = "knowledge_chunk"
    QA_PAIR = "qa_pair"
    PRODUCT = "product"
    MARKETING_DOCUMENT = "marketing_document"
    IMAGE = "image"


@dataclass(frozen=True, slots=True)
class VectorSearchResult:
    point_id: str
    score: float
    payload: dict[str, Any]


class VectorSearchService:
    """所有业务模块共用的向量检索门面。

    业务代码只负责准备文本、tenant_id、业务 ID 和 metadata。
    本服务统一负责 embedding、Qdrant collection 映射、写入、检索、删除和链路日志。
    """

    def __init__(
        self,
        *,
        qdrant_client: QdrantVectorClient | None = None,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self.qdrant = qdrant_client or QdrantVectorClient()
        self.embedding = embedding_client or EmbeddingClient()

    async def upsert_text(
        self,
        *,
        domain: VectorDomain,
        tenant_id: int,
        business_id: str | int,
        text: str,
        payload: dict[str, Any] | None = None,
        point_id: str | None = None,
    ) -> str | None:
        clean_text = str(text or "").strip()
        if not clean_text:
            logger.info(
                "Vector upsert skipped: domain=%s tenant_id=%s business_id=%s reason=empty_text",
                domain,
                tenant_id,
                business_id,
            )
            return None
        if not settings.AI_EMBEDDING_ENABLED or not settings.QDRANT_ENABLED:
            logger.info(
                "Vector upsert skipped: domain=%s tenant_id=%s business_id=%s embedding_enabled=%s qdrant_enabled=%s",
                domain,
                tenant_id,
                business_id,
                settings.AI_EMBEDDING_ENABLED,
                settings.QDRANT_ENABLED,
            )
            return None

        collection = self.collection_for(domain)
        resolved_point_id = point_id or self.make_point_id(domain, tenant_id, business_id)
        vector_payload = {
            "tenant_id": tenant_id,
            "domain": domain.value,
            "business_id": str(business_id),
            "text": clean_text,
            **(payload or {}),
        }

        try:
            vector = await self.embedding.embed(clean_text)
            stored_point_id = await self.qdrant.upsert(
                collection=collection,
                point_id=resolved_point_id,
                vector=vector,
                payload=vector_payload,
            )
        except (EmbeddingClientError, QdrantClientError, OSError) as exc:
            logger.warning(
                "Vector upsert failed: domain=%s tenant_id=%s business_id=%s error=%s",
                domain,
                tenant_id,
                business_id,
                exc,
            )
            return None

        logger.info(
            "Vector upsert indexed: domain=%s collection=%s tenant_id=%s business_id=%s point_id=%s",
            domain,
            collection,
            tenant_id,
            business_id,
            stored_point_id,
        )
        return stored_point_id

    async def search_text(
        self,
        *,
        domain: VectorDomain,
        tenant_id: int,
        query: str,
        top_k: int,
        min_score: float | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        clean_query = str(query or "").strip()
        if not clean_query:
            return []
        if not settings.AI_EMBEDDING_ENABLED or not settings.QDRANT_ENABLED:
            logger.info(
                "Vector search skipped: domain=%s tenant_id=%s embedding_enabled=%s qdrant_enabled=%s",
                domain,
                tenant_id,
                settings.AI_EMBEDDING_ENABLED,
                settings.QDRANT_ENABLED,
            )
            return []

        collection = self.collection_for(domain)
        search_filters = {"tenant_id": tenant_id, "domain": domain.value, **(filters or {})}
        try:
            vector = await self.embedding.embed(clean_query)
            hits = await self.qdrant.search(
                collection=collection,
                vector=vector,
                filters=search_filters,
                top_k=top_k,
                min_score=min_score,
            )
        except (EmbeddingClientError, QdrantClientError, OSError) as exc:
            logger.warning(
                "Vector search failed: domain=%s collection=%s tenant_id=%s query=%s error=%s",
                domain,
                collection,
                tenant_id,
                clean_query[:80],
                exc,
            )
            return []

        results = [
            VectorSearchResult(point_id=hit.point_id, score=hit.score, payload=hit.payload)
            for hit in hits
        ]
        logger.info(
            "Vector search results: domain=%s collection=%s tenant_id=%s query_len=%s hits=%s",
            domain,
            collection,
            tenant_id,
            len(clean_query),
            len(results),
        )
        return results

    async def delete_points(
        self,
        *,
        domain: VectorDomain,
        tenant_id: int,
        point_ids: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> None:
        collection = self.collection_for(domain)
        delete_filters = {"tenant_id": tenant_id, "domain": domain.value, **(filters or {})}
        try:
            await self.qdrant.delete(
                collection=collection,
                point_ids=point_ids,
                filters=None if point_ids else delete_filters,
            )
        except QdrantClientError as exc:
            logger.warning(
                "Vector delete failed: domain=%s collection=%s tenant_id=%s point_ids=%s filters=%s error=%s",
                domain,
                collection,
                tenant_id,
                len(point_ids or []),
                filters or {},
                exc,
            )

    def collection_for(self, domain: VectorDomain) -> str:
        return {
            VectorDomain.INTENT_SAMPLE: settings.QDRANT_COLLECTION_INTENT_SAMPLES,
            VectorDomain.KNOWLEDGE_CHUNK: settings.QDRANT_COLLECTION_KNOWLEDGE_CHUNKS,
            VectorDomain.QA_PAIR: settings.QDRANT_COLLECTION_QA_PAIRS,
            VectorDomain.PRODUCT: settings.QDRANT_COLLECTION_PRODUCTS,
            VectorDomain.MARKETING_DOCUMENT: settings.QDRANT_COLLECTION_MARKETING_DOCS,
            VectorDomain.IMAGE: settings.QDRANT_COLLECTION_IMAGES,
        }[domain]

    def make_point_id(self, domain: VectorDomain, tenant_id: int, business_id: str | int) -> str:
        raw = f"{domain.value}:{tenant_id}:{business_id}"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))
