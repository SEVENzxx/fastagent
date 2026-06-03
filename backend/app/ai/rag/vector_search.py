"""向量检索统一门面 — embedding + Qdrant 写 / 查 / 删。

业务方只需传文本 + tenant_id + 业务 ID，本服务负责 embedding、collection 映射、Qdrant 交互。
6 个 domain 对应 6 个 Qdrant collection，通过 tenant_id + domain 过滤实现多租户隔离。
"""

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
    """向量域 — 每个值对应一个 Qdrant collection。"""
    INTENT_SAMPLE = "intent_sample"
    KNOWLEDGE_CHUNK = "knowledge_chunk"
    QA_PAIR = "qa_pair"
    PRODUCT = "product"
    MARKETING_DOCUMENT = "marketing_document"
    IMAGE = "image"


@dataclass(frozen=True, slots=True)
class VectorSearchResult:
    """Qdrant 检索结果。"""
    point_id: str
    score: float
    payload: dict[str, Any]


class VectorSearchService:
    """向量检索统一入口。"""

    def __init__(
        self,
        *,
        qdrant_client: QdrantVectorClient | None = None,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self.qdrant = qdrant_client or QdrantVectorClient()
        self.embedding = embedding_client or EmbeddingClient()

    # ═══════════════════════════ 写入 ═══════════════════════════

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
        """将文本 embedding 后写入 Qdrant，按 point_id 覆盖已有向量。

        1. 空文本 / embedding 服务禁用 → 跳过
        2. 调 embedding 服务 → 获得向量
        3. Qdrant upsert（同 point_id 覆盖，不产生重复）
        """
        # ── 1: 跳过条件 ──
        clean_text = str(text or "").strip()
        if not clean_text:
            return None
        if not settings.AI_EMBEDDING_ENABLED or not settings.QDRANT_ENABLED:
            return None

        # ── 2: 准备 payload ──
        collection = self.collection_for(domain)
        resolved_point_id = point_id or self.make_point_id(domain, tenant_id, business_id)
        vector_payload = {
            "tenant_id": tenant_id,
            "domain": domain.value,
            "business_id": str(business_id),
            "text": clean_text,
            **(payload or {}),
        }

        # ── 3: embedding + upsert ──
        try:
            vector = await self.embedding.embed(clean_text)
            stored_point_id = await self.qdrant.upsert(
                collection=collection,
                point_id=resolved_point_id,
                vector=vector,
                payload=vector_payload,
            )
            return stored_point_id
        except (EmbeddingClientError, QdrantClientError, OSError) as exc:
            logger.warning(
                "Vector upsert failed: domain=%s tenant_id=%s business_id=%s error=%s",
                domain, tenant_id, business_id, exc,
            )
            return None

    # ═══════════════════════════ 检索 ═══════════════════════════

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
        """将 query embedding 后在 Qdrant 中检索 top_k 相似向量。

        1. 空 query / embedding 服务禁用 → 返回 []
        2. query embedding → Qdrant search（按 tenant_id + domain + 自定义 filters 过滤）
        """
        # ── 1: 跳过条件 ──
        clean_query = str(query or "").strip()
        if not clean_query:
            return []
        if not settings.AI_EMBEDDING_ENABLED or not settings.QDRANT_ENABLED:
            return []

        # ── 2: embedding + search ──
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
                "Vector search failed: domain=%s tenant_id=%s query_len=%s error=%s",
                domain, tenant_id, len(clean_query), exc,
            )
            return []

        return [
            VectorSearchResult(point_id=hit.point_id, score=hit.score, payload=hit.payload)
            for hit in hits
        ]

    # ═══════════════════════════ 删除 / 计数 ═══════════════════════════

    async def delete_points(
        self,
        *,
        domain: VectorDomain,
        tenant_id: int,
        point_ids: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> None:
        """按 point_id 列表或过滤条件删除向量点。"""
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
                "Vector delete failed: domain=%s tenant_id=%s error=%s",
                domain, tenant_id, exc,
            )

    async def count_points(self, domain: VectorDomain, tenant_id: int) -> int:
        """统计集合中指定租户的向量点数量。"""
        collection = self.collection_for(domain)
        try:
            return await self.qdrant.count(collection=collection, filters={"tenant_id": tenant_id})
        except QdrantClientError:
            return 0

    # ═══════════════════════════ 辅助 ═══════════════════════════

    def collection_for(self, domain: VectorDomain) -> str:
        """VectorDomain → Qdrant collection 名称。"""
        return {
            VectorDomain.INTENT_SAMPLE: settings.QDRANT_COLLECTION_INTENT_SAMPLES,
            VectorDomain.KNOWLEDGE_CHUNK: settings.QDRANT_COLLECTION_KNOWLEDGE_CHUNKS,
            VectorDomain.QA_PAIR: settings.QDRANT_COLLECTION_QA_PAIRS,
            VectorDomain.PRODUCT: settings.QDRANT_COLLECTION_PRODUCTS,
            VectorDomain.MARKETING_DOCUMENT: settings.QDRANT_COLLECTION_MARKETING_DOCS,
            VectorDomain.IMAGE: settings.QDRANT_COLLECTION_IMAGES,
        }[domain]

    def make_point_id(self, domain: VectorDomain, tenant_id: int, business_id: str | int) -> str:
        """生成确定性的 UUID5 point_id — 同 (domain, tenant_id, business_id) 总返回同一个 ID。"""
        raw = f"{domain.value}:{tenant_id}:{business_id}"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))
