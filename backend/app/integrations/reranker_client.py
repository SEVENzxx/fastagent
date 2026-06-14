"""Reranker 客户端 — Cross-Encoder 重排序（自部署 8002 / Qwen API）"""

from __future__ import annotations

import logging
import time

from app.ai.observability import observe_external_http, set_observation_io
from app.common.trace.context import get_trace_id
from app.config import settings
from app.integrations.base import BaseClient, BaseClientError

logger = logging.getLogger(__name__)


class RerankerClientError(RuntimeError):
    """Reranker 错误"""


class RerankerClient(BaseClient):
    """Cross-Encoder 模型重排序。

    支持两种 provider（通过 AI_RERANKER_PROVIDER 切换）：
    - http: 自部署 8002 服务 POST /rerank
    - qwen: 通义千问 DashScope Rerank API

    异常时降级为返回空列表（调用方按原始向量 score 排序）。
    """

    DEFAULT_TIMEOUT_SECONDS: float = 10.0

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url or settings.AI_RERANKER_BASE_URL,
            timeout_seconds=timeout_seconds or settings.AI_RERANKER_TIMEOUT_SECONDS,
            trust_env=False,
        )
        self.provider = settings.AI_RERANKER_PROVIDER
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
        async with observe_external_http(
            "reranker",
            "POST",
            f"{self.base_url}/rerank",
            docs_count=len(documents),
            top_k=top_k,
            input_data=_summarize_rerank_input(query, documents, top_k),
        ) as observation:
            started = time.perf_counter()
            try:
                data = await self._post("/rerank", json_body={
                    "query": query, "documents": documents, "top_k": top_k,
                })
            except BaseClientError as exc:
                logger.warning(
                    "Reranker HTTP 请求失败: %s, elapsed_ms=%.0f trace_id=%s",
                    exc,
                    (time.perf_counter() - started) * 1000,
                    get_trace_id(),
                )
                return []

        results = data.get("results") or []
        set_observation_io(observation, output_data=_summarize_rerank_output(results))
        logger.info(
            "Reranker 完成: query_len=%d docs=%d results=%d",
            len(query), len(documents), len(results),
        )
        return results

    async def _rerank_qwen(
        self, query: str, documents: list[str], top_k: int
    ) -> list[dict]:
        """调用通义千问 DashScope Rerank API。"""
        if not self.base_url:
            raise RerankerClientError("AI_RERANKER_BASE_URL 不能为空")

        async with observe_external_http(
            "reranker",
            "POST",
            self.base_url,
            docs_count=len(documents),
            top_k=top_k,
            input_data=_summarize_rerank_input(query, documents, top_k),
        ) as observation:
            started = time.perf_counter()
            try:
                data = await self._post("", json_body={
                    "model": settings.AI_RERANKER_MODEL,
                    "input": {"query": query, "documents": documents},
                    "parameters": {"top_n": top_k},
                })
            except BaseClientError as exc:
                logger.warning(
                    "Qwen Rerank API 请求失败: %s, elapsed_ms=%.0f trace_id=%s",
                    exc,
                    (time.perf_counter() - started) * 1000,
                    get_trace_id(),
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
        set_observation_io(observation, output_data=_summarize_rerank_output(formatted))
        logger.info(
            "Qwen Rerank 完成: docs=%d results=%d",
            len(documents), len(formatted),
        )
        return formatted


def _summarize_rerank_input(query: str, documents: list[str], top_k: int) -> dict:
    return {
        "query": str(query)[:500],
        "query_len": len(str(query)),
        "docs_count": len(documents),
        "docs_preview": [str(doc)[:300] for doc in documents[:3]],
        "top_k": top_k,
    }


def _summarize_rerank_output(results: list[dict]) -> dict:
    return {
        "result_count": len(results),
        "top_results": [
            {
                "index": item.get("index"),
                "score": item.get("score") or item.get("relevance_score"),
            }
            for item in results[:5]
            if isinstance(item, dict)
        ],
    }
