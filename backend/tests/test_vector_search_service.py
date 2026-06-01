from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.integrations.embedding_client import EmbeddingClientError
from app.integrations.qdrant_client import QdrantSearchHit
from app.services.vector_search_service import VectorDomain, VectorSearchService


@pytest.fixture(autouse=True)
def enable_vector_search(monkeypatch):
    monkeypatch.setattr(settings, "AI_EMBEDDING_ENABLED", True)
    monkeypatch.setattr(settings, "QDRANT_ENABLED", True)


@pytest.mark.asyncio
async def test_upsert_text_embeds_and_stores_tenant_scoped_payload():
    embedding = AsyncMock()
    embedding.embed.return_value = [0.1, 0.2]
    qdrant = AsyncMock()
    qdrant.upsert.return_value = "stored-point"
    service = VectorSearchService(qdrant_client=qdrant, embedding_client=embedding)

    result = await service.upsert_text(
        domain=VectorDomain.PRODUCT,
        tenant_id=7,
        business_id=42,
        text="  product manual  ",
        payload={"category": "docs"},
        point_id="point-42",
    )

    assert result == "stored-point"
    embedding.embed.assert_awaited_once_with("product manual")
    qdrant.upsert.assert_awaited_once_with(
        collection=settings.QDRANT_COLLECTION_PRODUCTS,
        point_id="point-42",
        vector=[0.1, 0.2],
        payload={
            "tenant_id": 7,
            "domain": "product",
            "business_id": "42",
            "text": "product manual",
            "category": "docs",
        },
    )


@pytest.mark.asyncio
async def test_search_text_adds_tenant_and_domain_filters():
    embedding = AsyncMock()
    embedding.embed.return_value = [0.3, 0.4]
    qdrant = AsyncMock()
    qdrant.search.return_value = [
        QdrantSearchHit(point_id="p1", score=0.91, payload={"name": "A"})
    ]
    service = VectorSearchService(qdrant_client=qdrant, embedding_client=embedding)

    result = await service.search_text(
        domain=VectorDomain.QA_PAIR,
        tenant_id=9,
        query=" refund ",
        top_k=3,
        min_score=0.8,
        filters={"is_active": True},
    )

    assert [(hit.point_id, hit.score, hit.payload) for hit in result] == [
        ("p1", 0.91, {"name": "A"})
    ]
    qdrant.search.assert_awaited_once_with(
        collection=settings.QDRANT_COLLECTION_QA_PAIRS,
        vector=[0.3, 0.4],
        filters={"tenant_id": 9, "domain": "qa_pair", "is_active": True},
        top_k=3,
        min_score=0.8,
    )


@pytest.mark.asyncio
async def test_search_text_degrades_to_empty_results_when_embedding_fails():
    embedding = AsyncMock()
    embedding.embed.side_effect = EmbeddingClientError("offline")
    qdrant = AsyncMock()
    service = VectorSearchService(qdrant_client=qdrant, embedding_client=embedding)

    result = await service.search_text(
        domain=VectorDomain.KNOWLEDGE_CHUNK,
        tenant_id=1,
        query="question",
        top_k=5,
    )

    assert result == []
    qdrant.search.assert_not_awaited()
