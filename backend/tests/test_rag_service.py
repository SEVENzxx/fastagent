from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.services.rag_service import RAGService
from app.services.vector_search_service import VectorDomain, VectorSearchResult


@pytest.mark.asyncio
async def test_search_chunks_reranks_vector_candidates(monkeypatch):
    monkeypatch.setattr(settings, "AI_RERANKER_ENABLED", True)
    service = RAGService()
    service.vector_search.search_text = AsyncMock(
        return_value=[
            VectorSearchResult("p1", 0.92, {"chunk_id": "1", "text": "first"}),
            VectorSearchResult("p2", 0.81, {"chunk_id": "2", "text": "second"}),
        ]
    )
    service.reranker_client.rerank = AsyncMock(
        return_value=[
            {"index": 1, "score": 0.99},
            {"index": 0, "score": 0.75},
        ]
    )

    result = await service.search_chunks("question", tenant_id=12)

    assert [item["id"] for item in result] == ["2", "1"]
    assert [item["score"] for item in result] == [0.99, 0.75]
    service.vector_search.search_text.assert_awaited_once_with(
        domain=VectorDomain.KNOWLEDGE_CHUNK,
        tenant_id=12,
        query="question",
        top_k=service.top_k,
        min_score=service.min_score,
    )


@pytest.mark.asyncio
async def test_search_chunks_falls_back_to_vector_order_when_reranker_fails(monkeypatch):
    monkeypatch.setattr(settings, "AI_RERANKER_ENABLED", True)
    service = RAGService()
    service.vector_search.search_text = AsyncMock(
        return_value=[
            VectorSearchResult("p1", 0.92, {"chunk_id": "1", "text": "first"}),
            VectorSearchResult("p2", 0.81, {"chunk_id": "2", "text": "second"}),
        ]
    )
    service.reranker_client.rerank = AsyncMock(side_effect=RuntimeError("offline"))

    result = await service.search_chunks("question", tenant_id=12)

    assert [item["id"] for item in result] == ["1", "2"]


@pytest.mark.asyncio
async def test_search_combines_chunks_and_active_qa_matches():
    service = RAGService()
    service.vector_search.search_text = AsyncMock(
        side_effect=[
            [VectorSearchResult("chunk", 0.9, {"chunk_id": "c1", "text": "manual"})],
            [
                VectorSearchResult(
                    "qa",
                    0.95,
                    {"qa_id": "q1", "question": "How?", "answer": "Like this."},
                )
            ],
        ]
    )

    result = await service.search("question", tenant_id=2)

    assert result["chunks"][0]["id"] == "c1"
    assert result["qa_matches"][0]["answer"] == "Like this."
    assert service.vector_search.search_text.await_args_list[1].kwargs["filters"] == {
        "is_active": True
    }
