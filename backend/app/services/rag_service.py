"""基于 Qdrant 的 RAG 检索服务。"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.integrations.reranker_client import RerankerClient
from app.ai.rag.vector_search import VectorDomain, VectorSearchResult, VectorSearchService

logger = logging.getLogger(__name__)


class RAGService:
    """知识检索编排服务。

    Qdrant 是唯一向量数据库。PostgreSQL 保存原始文档和分块业务数据，
    语义召回从 Qdrant payload 中读取检索字段。
    """

    def __init__(self) -> None:
        self.vector_search = VectorSearchService()
        self.reranker_client = RerankerClient()
        self.top_k = settings.AI_KNOWLEDGE_TOP_K
        self.min_score = settings.AI_KNOWLEDGE_MIN_SCORE
        self.rerank_top_k = settings.AI_KNOWLEDGE_RERANK_TOP_K
        self.qa_top_k = settings.AI_KNOWLEDGE_QA_TOP_K
        self.qa_min_score = settings.AI_KNOWLEDGE_QA_MIN_SCORE

    async def search_chunks(self, query: str, tenant_id: int, db: AsyncSession | None = None) -> list[dict]:
        """从 Qdrant 召回知识分块，并按配置进行 rerank。"""
        _ = db
        hits = await self.vector_search.search_text(
            domain=VectorDomain.KNOWLEDGE_CHUNK,
            tenant_id=tenant_id,
            query=query,
            top_k=self.top_k,
            min_score=self.min_score,
        )
        candidates = [self._chunk_hit_to_dict(hit) for hit in hits]
        if not candidates:
            return []

        if settings.AI_RERANKER_ENABLED and len(candidates) > 1:
            try:
                doc_texts = [item["content"] for item in candidates]
                reranked = await self.reranker_client.rerank(query, doc_texts, self.rerank_top_k)
                if reranked:
                    results = []
                    for item in reranked:
                        idx = item.get("index", 0)
                        if 0 <= idx < len(candidates):
                            candidate = candidates[idx]
                            candidate["score"] = round(float(item.get("score", candidate.get("score", 0))), 4)
                            results.append(candidate)
                    logger.info("RAG chunk search reranked: tenant_id=%s query=%s hits=%s", tenant_id, query[:80], len(results))
                    return results[: self.rerank_top_k]
            except Exception as exc:
                logger.warning("RAG reranker failed, using Qdrant scores: %s", exc)

        return candidates[: self.rerank_top_k]

    async def search_qa(self, query: str, tenant_id: int, db: AsyncSession | None = None) -> list[dict]:
        """在 Qdrant 中匹配启用中的标准问答对。"""
        _ = db
        hits = await self.vector_search.search_text(
            domain=VectorDomain.QA_PAIR,
            tenant_id=tenant_id,
            query=query,
            top_k=self.qa_top_k,
            min_score=self.qa_min_score,
            filters={"is_active": True},
        )
        logger.info(
            "QA search params: query=%r tenant_id=%s top_k=%s min_score=%s",
            query,
            tenant_id,
            self.qa_top_k,
            self.qa_min_score,
        )
        return [self._qa_hit_to_dict(hit) for hit in hits]

    async def search(self, query: str, tenant_id: int, db: AsyncSession | None = None) -> dict:
        chunks = await self.search_chunks(query, tenant_id, db)
        qa_matches = await self.search_qa(query, tenant_id, db)
        logger.info(
            "RAG search complete: tenant_id=%s query=%s chunks=%s qa=%s",
            tenant_id,
            query[:80],
            len(chunks),
            len(qa_matches),
        )
        return {"chunks": chunks, "qa_matches": qa_matches}

    def _chunk_hit_to_dict(self, hit: VectorSearchResult) -> dict:
        payload = hit.payload
        return {
            "id": str(payload.get("chunk_id") or payload.get("business_id") or hit.point_id),
            "doc_id": str(payload.get("doc_id") or ""),
            "chunk_index": payload.get("chunk_index"),
            "content": str(payload.get("text") or ""),
            "token_count": payload.get("token_count"),
            "metadata": payload.get("metadata") or {},
            "score": hit.score,
            "qdrant_point_id": hit.point_id,
        }

    def _qa_hit_to_dict(self, hit: VectorSearchResult) -> dict:
        payload = hit.payload
        return {
            "id": str(payload.get("qa_id") or payload.get("business_id") or hit.point_id),
            "question": str(payload.get("question") or payload.get("text") or ""),
            "answer": str(payload.get("answer") or ""),
            "keywords": payload.get("keywords") or [],
            "score": hit.score,
            "qdrant_point_id": hit.point_id,
        }
