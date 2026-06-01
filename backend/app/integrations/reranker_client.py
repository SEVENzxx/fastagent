"""Reranker 客户端 — Cross-Encoder 重排序（自部署 8002 / Qwen API）"""

from __future__ import annotations

import logging
import time

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class RerankerClientError(RuntimeError):
    """Reranker 错误"""


class RerankerClient:
    """Cross-Encoder 模型重排序。

    支持两种 provider（通过 AI_RERANKER_PROVIDER 切换）：
    - http: 自部署 8002 服务 POST /rerank
    - qwen: 通义千问 DashScope Rerank API

    异常时降级为返回空列表（调用方按原始向量 score 排序）。
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.provider = settings.AI_RERANKER_PROVIDER
        self.base_url = (base_url or settings.AI_RERANKER_BASE_URL).rstrip("/")
        self.timeout = timeout_seconds or settings.AI_RERANKER_TIMEOUT_SECONDS
        self.enabled = settings.AI_RERANKER_ENABLED

    async def rerank(
        self, query: str, documents: list[str], top_k: int | None = None
    ) -> list[dict]:
        """对 query-document 对重排序，返回 [{index, score, document}, ...]。

        top_k 默认取 config.AI_KNOWLEDGE_RERANK_TOP_K。
        """
        if top_k is None:
            top_k = settings.AI_KNOWLEDGE_RERANK_TOP_K

        if not self.enabled or not documents:
            return []

        if self.provider == "http":
            return await self._rerank_http(query, documents, top_k)
        if self.provider == "qwen":
            return await self._rerank_qwen(query, documents, top_k)

        logger.warning("未知 reranker provider: %s，跳过重排序", self.provider)
        return []

    async def _rerank_http(
        self, query: str, documents: list[str], top_k: int
    ) -> list[dict]:
        """调用自部署 8002 reranker。"""
        url = f"{self.base_url}/rerank"
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                resp = await client.post(
                    url,
                    json={"query": query, "documents": documents, "top_k": top_k},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning(
                "Reranker HTTP 请求失败: %s, elapsed_ms=%.0f",
                exc,
                (time.perf_counter() - started) * 1000,
            )
            return []
        except ValueError:
            logger.warning("Reranker 返回非 JSON")
            return []

        results = data.get("results") or []
        logger.info(
            "Reranker 完成: query_len=%d docs=%d results=%d elapsed_ms=%.0f",
            len(query),
            len(documents),
            len(results),
            (time.perf_counter() - started) * 1000,
        )
        return results

    async def _rerank_qwen(
        self, query: str, documents: list[str], top_k: int
    ) -> list[dict]:
        """调用通义千问 DashScope Rerank API。"""
        if not self.base_url:
            raise RerankerClientError("AI_RERANKER_BASE_URL 不能为空")

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                resp = await client.post(
                    self.base_url,
                    json={
                        "model": settings.AI_RERANKER_MODEL,
                        "input": {"query": query, "documents": documents},
                        "parameters": {"top_n": top_k},
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning(
                "Qwen Rerank API 请求失败: %s, elapsed_ms=%.0f",
                exc,
                (time.perf_counter() - started) * 1000,
            )
            return []

        results = data.get("output", {}).get("results") or []
        formatted = []
        for item in results:
            idx = item.get("index")
            if idx is not None and idx < len(documents):
                formatted.append({
                    "index": idx,
                    "score": item.get("relevance_score", 0),
                    "document": documents[idx],
                })
        logger.info(
            "Qwen Rerank 完成: docs=%d results=%d elapsed_ms=%.0f",
            len(documents),
            len(formatted),
            (time.perf_counter() - started) * 1000,
        )
        return formatted
