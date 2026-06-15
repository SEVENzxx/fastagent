"""基于 Qdrant 的 RAG 检索服务。"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.query_rewriter import normalize_query
from app.ai.rag.vector_search import VectorDomain, VectorSearchResult, VectorSearchService
from app.config import settings
from app.integrations.reranker_client import RerankerClient

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
        normalized_query = normalize_query(query)
        hits = await self.vector_search.search_text(
            domain=VectorDomain.KNOWLEDGE_CHUNK,
            tenant_id=tenant_id,
            query=normalized_query,
            top_k=self.top_k,
            min_score=self.min_score,
        )
        candidates = [self._chunk_hit_to_dict(hit) for hit in hits]
        logger.info(
            "RAG chunk 召回：raw_query=%r normalized_query=%r tenant_id=%s top_k=%s min_score=%s candidates=%s scores=%s enter_reranker=%s",
            query,
            normalized_query,
            tenant_id,
            self.top_k,
            self.min_score,
            len(candidates),
            [round(float(item.get("score", 0)), 4) for item in candidates[:10]],
            settings.AI_RERANKER_ENABLED and len(candidates) > 1,
        )
        if not candidates:
            return []

        if settings.AI_RERANKER_ENABLED and len(candidates) > 1:
            try:
                doc_texts = [item["content"] for item in candidates]
                reranked = await self.reranker_client.rerank(normalized_query, doc_texts, self.rerank_top_k)
                if reranked:
                    results = []
                    for item in reranked:
                        idx = item.get("index", 0)
                        if 0 <= idx < len(candidates):
                            candidate = candidates[idx]
                            candidate["score"] = round(float(item.get("score", candidate.get("score", 0))), 4)
                            results.append(candidate)
                    logger.info(
                        "RAG chunk rerank 完成：tenant_id=%s query=%s hits=%s rerank_scores=%s",
                        tenant_id,
                        normalized_query[:80],
                        len(results),
                        [item.get("score") for item in reranked[: self.rerank_top_k]],
                    )
                    return results[: self.rerank_top_k]
            except Exception as exc:
                logger.warning("RAG 重排序失败，降级使用 Qdrant 分数: %s", exc)

        return candidates[: self.rerank_top_k]

    async def search_qa(self, query: str, tenant_id: int, db: AsyncSession | None = None) -> list[dict]:
        """在 Qdrant 中匹配启用中的标准问答对。"""
        _ = db
        normalized_query = normalize_query(query)
        hits = await self.vector_search.search_text(
            domain=VectorDomain.QA_PAIR,
            tenant_id=tenant_id,
            query=normalized_query,
            top_k=self.qa_top_k,
            min_score=self.qa_min_score,
            filters={"is_active": True},
        )
        logger.info(
            "QA search params: raw_query=%r normalized_query=%r tenant_id=%s top_k=%s min_score=%s candidates=%s scores=%s direct_answer=%s",
            query,
            normalized_query,
            tenant_id,
            self.qa_top_k,
            self.qa_min_score,
            len(hits),
            [round(hit.score, 4) for hit in hits],
            bool(hits),
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
        """将 Qdrant 召回的知识分块 hit 转为前端可用的字典。"""
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
        """将 Qdrant 召回的 QA 对 hit 转为前端可用的字典。"""
        payload = hit.payload
        return {
            "id": str(payload.get("qa_id") or payload.get("business_id") or hit.point_id),
            "question": str(payload.get("question") or payload.get("text") or ""),
            "answer": str(payload.get("answer") or ""),
            "keywords": payload.get("keywords") or [],
            "score": hit.score,
            "qdrant_point_id": hit.point_id,
        }
