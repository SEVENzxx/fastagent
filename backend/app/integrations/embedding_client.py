"""Embedding HTTP 客户端。"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.ai.observability import observe_external_http, set_observation_io
from app.common.trace.context import get_trace_id
from app.config import settings
from app.integrations.base import BaseClient, BaseClientError

logger = logging.getLogger(__name__)


class EmbeddingClientError(RuntimeError):
    """Embedding 服务不可用、请求失败或返回格式异常时抛出。"""


class EmbeddingClient(BaseClient):
    """调用平台托管的 BGE embedding 服务。

    服务默认地址由 `.env` 中的 `AI_EMBEDDING_BASE_URL` 控制，当前约定接口为
    `{base_url}/embed`。客户端同时兼容单条 `{"text": "..."}` 和批量
    `{"texts": ["...", "..."]}` 的常见返回格式。
    """

    DEFAULT_TIMEOUT_SECONDS: float = 5.0

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url or settings.AI_EMBEDDING_BASE_URL,
            timeout_seconds=timeout_seconds or settings.AI_EMBEDDING_TIMEOUT_SECONDS,
            trust_env=False,
        )

    async def embed(self, text: str) -> list[float]:
        """返回单条文本向量。"""
        embeddings = await self.embed_many([text])
        if not embeddings:
            raise EmbeddingClientError("Embedding 响应为空")
        return embeddings[0]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        """批量返回文本向量。"""
        clean_texts = [str(item or "").strip() for item in texts]
        if not clean_texts:
            return []

        async with observe_external_http(
            "embedding",
            "POST",
            "/embed",
            texts_count=len(clean_texts),
            input_data={
                "texts_count": len(clean_texts),
                "text_lens": [len(text) for text in clean_texts[:10]],
                "texts_preview": [text[:300] for text in clean_texts[:3]],
            },
        ) as observation:
            data = await self._post_json("/embed", {"texts": clean_texts})
        embeddings = self._extract_embeddings(data)
        set_observation_io(
            observation,
            output_data={
                "vectors": len(embeddings),
                "dimensions": len(embeddings[0]) if embeddings else 0,
            },
        )
        if len(embeddings) == len(clean_texts):
            logger.info("Embedding 请求完成：texts=%s vectors=%s", len(clean_texts), len(embeddings))
            return embeddings

        # 兼容只支持单条 text 的服务实现。
        if len(clean_texts) == 1 and len(embeddings) == 1:
            logger.info("Embedding 请求完成：texts=%s vectors=%s", len(clean_texts), len(embeddings))
            return embeddings

        logger.warning("Embedding 返回数量不匹配：expected=%s actual=%s", len(clean_texts), len(embeddings))
        raise EmbeddingClientError(
            f"Embedding 返回数量不匹配：expected={len(clean_texts)}, actual={len(embeddings)}"
        )

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON 请求，统一异常转换为 EmbeddingClientError。"""
        if not self.base_url:
            raise EmbeddingClientError("AI_EMBEDDING_BASE_URL 不能为空")

        started = time.perf_counter()
        try:
            data = await self._post(path, json_body=payload)
        except BaseClientError as exc:
            logger.warning(
                "Embedding HTTP 请求失败：path=%s elapsed_ms=%.0f trace_id=%s error=%s",
                path,
                (time.perf_counter() - started) * 1000,
                get_trace_id(),
                exc,
            )
            raise EmbeddingClientError(f"Embedding HTTP 错误：{exc}") from exc

        if not isinstance(data, dict):
            raise EmbeddingClientError("Embedding 响应必须是 JSON 对象")
        logger.info(
            "Embedding HTTP 请求完成：path=%s elapsed_ms=%.0f trace_id=%s",
            path,
            (time.perf_counter() - started) * 1000,
            get_trace_id(),
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

        raise EmbeddingClientError("Embedding 响应中不包含向量")

    def _is_vector(self, value: Any) -> bool:
        return isinstance(value, list) and bool(value) and all(isinstance(item, int | float) for item in value)

    def _to_vector(self, value: Any) -> list[float]:
        if not self._is_vector(value):
            raise EmbeddingClientError("无效的 Embedding 向量")
        return [float(item) for item in value]
