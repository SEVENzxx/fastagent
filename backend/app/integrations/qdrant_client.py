"""Qdrant HTTP 集成层。

所有 Qdrant 原始调用都集中在这里。业务服务应通过 VectorSearchService
使用向量能力，不要直接拼装 Qdrant 请求。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class QdrantClientError(RuntimeError):
    """Qdrant 未启用、不可用或返回非法数据时抛出。"""


@dataclass(frozen=True, slots=True)
class QdrantSearchHit:
    point_id: str
    score: float
    payload: dict[str, Any]


class QdrantVectorClient:
    """供统一向量检索服务使用的轻量异步 Qdrant REST 客户端。"""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        vector_size: int | None = None,
        distance: str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.QDRANT_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.QDRANT_API_KEY
        self.timeout_seconds = timeout_seconds or settings.QDRANT_TIMEOUT_SECONDS
        self.vector_size = vector_size or settings.AI_EMBEDDING_DIMENSION
        self.distance = distance or settings.QDRANT_DISTANCE
        self.enabled = settings.QDRANT_ENABLED

    async def ensure_collection(self, collection: str) -> None:
        """确保 collection 存在，不存在时自动创建。"""
        if not self.enabled:
            raise QdrantClientError("Qdrant is disabled")

        started = time.perf_counter()
        exists = await self._collection_exists(collection)
        if exists:
            logger.info("Qdrant collection exists: collection=%s", collection)
            return

        payload = {
            "vectors": {
                "size": self.vector_size,
                "distance": self.distance,
            }
        }
        await self._request("PUT", f"/collections/{collection}", json=payload)
        logger.info(
            "Qdrant collection created: collection=%s size=%s distance=%s elapsed_ms=%.0f",
            collection,
            self.vector_size,
            self.distance,
            (time.perf_counter() - started) * 1000,
        )

    async def upsert(
        self,
        *,
        collection: str,
        point_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> str:
        """写入或更新单个向量点，并返回 point id。"""
        self._validate_vector(vector)
        await self.ensure_collection(collection)
        started = time.perf_counter()
        body = {
            "points": [
                {
                    "id": point_id,
                    "vector": vector,
                    "payload": payload,
                }
            ]
        }
        await self._request("PUT", f"/collections/{collection}/points", json=body)
        logger.info(
            "Qdrant upsert complete: collection=%s point_id=%s elapsed_ms=%.0f",
            collection,
            point_id,
            (time.perf_counter() - started) * 1000,
        )
        return point_id

    async def search(
        self,
        *,
        collection: str,
        vector: list[float],
        filters: dict[str, Any] | None = None,
        top_k: int = 10,
        min_score: float | None = None,
    ) -> list[QdrantSearchHit]:
        """在指定 collection 中检索，支持 payload 精确过滤。"""
        self._validate_vector(vector)
        await self.ensure_collection(collection)
        started = time.perf_counter()
        body: dict[str, Any] = {
            "vector": vector,
            "limit": top_k,
            "with_payload": True,
        }
        if min_score is not None:
            body["score_threshold"] = min_score
        qdrant_filter = self._to_qdrant_filter(filters)
        if qdrant_filter:
            body["filter"] = qdrant_filter

        data = await self._request("POST", f"/collections/{collection}/points/search", json=body)
        result = data.get("result", [])
        if not isinstance(result, list):
            raise QdrantClientError("Qdrant search result must be a list")

        hits = [
            QdrantSearchHit(
                point_id=str(item.get("id")),
                score=round(float(item.get("score") or 0.0), 4),
                payload=item.get("payload") if isinstance(item.get("payload"), dict) else {},
            )
            for item in result
            if isinstance(item, dict)
        ]
        logger.info(
            "Qdrant search complete: collection=%s filters=%s top_k=%s hits=%s elapsed_ms=%.0f",
            collection,
            filters or {},
            top_k,
            len(hits),
            (time.perf_counter() - started) * 1000,
        )
        return hits

    async def delete(
        self,
        *,
        collection: str,
        point_ids: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> None:
        """按 point id 或 payload 精确过滤条件删除向量点。"""
        await self.ensure_collection(collection)
        started = time.perf_counter()
        if point_ids:
            selector: dict[str, Any] = {"points": point_ids}
        else:
            qdrant_filter = self._to_qdrant_filter(filters)
            if not qdrant_filter:
                raise QdrantClientError("delete requires point_ids or filters")
            selector = {"filter": qdrant_filter}
        await self._request("POST", f"/collections/{collection}/points/delete", json=selector)
        logger.info(
            "Qdrant delete complete: collection=%s point_ids=%s filters=%s elapsed_ms=%.0f",
            collection,
            len(point_ids or []),
            filters or {},
            (time.perf_counter() - started) * 1000,
        )

    async def _collection_exists(self, collection: str) -> bool:
        try:
            await self._request("GET", f"/collections/{collection}")
            return True
        except QdrantClientError as exc:
            if "status=404" in str(exc):
                return False
            raise

    async def _request(self, method: str, path: str, *, json: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.enabled:
            raise QdrantClientError("Qdrant is disabled")
        if not self.base_url:
            raise QdrantClientError("QDRANT_URL must not be empty")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["api-key"] = self.api_key

        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False) as client:
                response = await client.request(method, url, headers=headers, json=json)
                if response.status_code >= 400:
                    raise QdrantClientError(f"Qdrant HTTP error: status={response.status_code} body={response.text[:300]}")
                data = response.json() if response.content else {}
        except httpx.HTTPError as exc:
            raise QdrantClientError(f"Qdrant HTTP error: {exc}") from exc
        except ValueError as exc:
            raise QdrantClientError("Qdrant response is not valid JSON") from exc

        if not isinstance(data, dict):
            raise QdrantClientError("Qdrant response must be a JSON object")
        return data

    def _validate_vector(self, vector: list[float]) -> None:
        if len(vector) != self.vector_size:
            raise QdrantClientError(f"invalid vector dimension: expected={self.vector_size}, actual={len(vector)}")

    def _to_qdrant_filter(self, filters: dict[str, Any] | None) -> dict[str, Any] | None:
        if not filters:
            return None
        must = []
        for key, value in filters.items():
            if value is None:
                continue
            must.append({"key": key, "match": {"value": value}})
        return {"must": must} if must else None
