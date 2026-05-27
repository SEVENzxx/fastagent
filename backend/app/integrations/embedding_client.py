"""Embedding HTTP 客户端。"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class EmbeddingClientError(RuntimeError):
    """Embedding 服务不可用、请求失败或返回格式异常时抛出。"""


class EmbeddingClient:
    """调用平台托管的 BGE embedding 服务。

    服务默认地址由 `.env` 中的 `AI_EMBEDDING_BASE_URL` 控制，当前约定接口为
    `{base_url}/embed`。客户端同时兼容单条 `{"text": "..."}` 和批量
    `{"texts": ["...", "..."]}` 的常见返回格式。
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.base_url = (base_url or settings.AI_EMBEDDING_BASE_URL).rstrip("/")
        self.timeout_seconds = timeout_seconds or settings.AI_EMBEDDING_TIMEOUT_SECONDS

    async def embed(self, text: str) -> list[float]:
        """返回单条文本向量。"""
        embeddings = await self.embed_many([text])
        if not embeddings:
            raise EmbeddingClientError("embedding response is empty")
        return embeddings[0]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        """批量返回文本向量。"""
        clean_texts = [str(item or "").strip() for item in texts]
        if not clean_texts:
            return []

        started = time.perf_counter()
        data = await self._post_json("/embed", {"texts": clean_texts})
        embeddings = self._extract_embeddings(data)
        if len(embeddings) == len(clean_texts):
            logger.info(
                "Embedding 请求完成：texts=%s vectors=%s elapsed_ms=%.0f",
                len(clean_texts),
                len(embeddings),
                (time.perf_counter() - started) * 1000,
            )
            return embeddings

        # 兼容只支持单条 text 的服务实现。
        if len(clean_texts) == 1 and len(embeddings) == 1:
            logger.info(
                "Embedding 请求完成：texts=1 vectors=1 elapsed_ms=%.0f",
                (time.perf_counter() - started) * 1000,
            )
            return embeddings

        logger.warning(
            "Embedding 返回数量不匹配：expected=%s actual=%s elapsed_ms=%.0f",
            len(clean_texts),
            len(embeddings),
            (time.perf_counter() - started) * 1000,
        )
        raise EmbeddingClientError(
            f"embedding count mismatch: expected={len(clean_texts)}, actual={len(embeddings)}"
        )

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.base_url:
            raise EmbeddingClientError("AI_EMBEDDING_BASE_URL 不能为空")

        url = f"{self.base_url}{path}"
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.warning(
                "Embedding HTTP 请求失败：path=%s elapsed_ms=%.0f error=%s",
                path,
                (time.perf_counter() - started) * 1000,
                exc,
            )
            raise EmbeddingClientError(f"embedding http error: {exc}") from exc
        except ValueError as exc:
            logger.warning(
                "Embedding 返回非 JSON：path=%s elapsed_ms=%.0f",
                path,
                (time.perf_counter() - started) * 1000,
            )
            raise EmbeddingClientError("embedding response is not valid json") from exc

        if not isinstance(data, dict):
            raise EmbeddingClientError("embedding response must be a json object")
        logger.info(
            "Embedding HTTP 请求完成：path=%s elapsed_ms=%.0f",
            path,
            (time.perf_counter() - started) * 1000,
        )
        return data

    def _extract_embeddings(self, data: dict[str, Any]) -> list[list[float]]:
        """兼容常见 embedding 服务返回字段。"""
        value = (
            data.get("embeddings")
            or data.get("vectors")
            or data.get("data")
            or data.get("embedding")
            or data.get("vector")
        )

        if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            value = [item.get("embedding") or item.get("vector") for item in value]

        if self._is_vector(value):
            return [self._to_vector(value)]

        if isinstance(value, list) and all(self._is_vector(item) for item in value):
            return [self._to_vector(item) for item in value]

        raise EmbeddingClientError("embedding response does not contain embeddings")

    def _is_vector(self, value: Any) -> bool:
        return isinstance(value, list) and bool(value) and all(isinstance(item, int | float) for item in value)

    def _to_vector(self, value: Any) -> list[float]:
        if not self._is_vector(value):
            raise EmbeddingClientError("invalid embedding vector")
        return [float(item) for item in value]
