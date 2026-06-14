"""VectorIntentRetriever：基于 Qdrant 的候选意图召回。

检索策略（v3 增强）：
  1. 同时搜索当前 tenant_id 和 tenant_id=0 的样本（而非先后 fallback）。
  2. 过滤 is_active=true，仅召回启用状态的样本。
  3. 合并去重（按 intent + example_text），租户专属样本 score +0.03 加权。
  4. 按 score 降序返回给引擎层。

意图样本写入：
  - 平台默认（tenant_id=0）：bootstrap.py 启动时统一写入
  - 租户自定义（tenant_id>0）：管理后台 API CRUD → 实时同步 Qdrant
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.ai.recognition.examples import DEFAULT_INTENT_EXAMPLES, IntentExample
from app.ai.rag.vector_search import VectorDomain, VectorSearchService, VectorSearchResult
from app.ai.recognition.config import DEFAULT_INTENT_CONFIG, IntentRecognitionConfig


@dataclass(frozen=True, slots=True)
class IntentCandidate:
    """Qdrant 向量召回产出的候选意图（内部类型）。"""
    intent: str
    label: str
    score: float
    source: str
    matched_text: str | None = None
    reason: str | None = None

logger = logging.getLogger(__name__)


class VectorIntentRetriever:
    """从 Qdrant 意图样本 collection 中召回候选意图。

    检索逻辑：
      1. 先按 tenant_id 查租户专属样本，有结果直接返回
      2. 专属样本无结果 → 查 tenant_id=0 的全局默认样本
      3. Qdrant 无结果 → 返回空列表，由引擎层走 LLM 判决

    注意：意图样本的写入不属于此类的职责，在 bootstrap.py 启动时处理。
    """

    def __init__(
        self,
        config: IntentRecognitionConfig | None = None,
        examples: Sequence[IntentExample] | None = None,
        vector_search: VectorSearchService | None = None,
    ) -> None:
        self.config = config or DEFAULT_INTENT_CONFIG
        self.examples = tuple(examples or DEFAULT_INTENT_EXAMPLES)
        self.vector_search = vector_search or VectorSearchService()

    async def retrieve(self, segment: str, *, tenant_id: int = 0) -> list[IntentCandidate]:
        """返回分数达到阈值的 top-k 候选意图。

        1. 查租户专属样本 (tenant_id)
        2. 无结果 → 查全局默认样本 (tenant_id=0)
        3. Qdrant 无结果 → 返回空列表
        """
        logger.info("意图召回：segment=%s tenant_id=%s", segment[:40], tenant_id)
        candidates = await self._search_qdrant(segment, tenant_id=tenant_id)
        if not candidates and tenant_id != 0:
            candidates = await self._search_qdrant(segment, tenant_id=0)

        return candidates

    async def _search_qdrant(self, segment: str, *, tenant_id: int) -> list[IntentCandidate]:
        """对指定 tenant_id 执行 Qdrant 向量检索（仅 is_active 样本）。"""
        hits = await self.vector_search.search_text(
            domain=VectorDomain.INTENT_SAMPLE,
            tenant_id=tenant_id,
            query=segment,
            top_k=self.config.vector_top_k,
            min_score=self.config.vector_min_score,
            filters={"is_active": True},
        )
        return [
            IntentCandidate(
                intent=str(hit.payload.get("intent") or ""),
                label=str(hit.payload.get("label") or ""),
                score=hit.score,
                source=f"qdrant_{hit.payload.get('source', 'unknown')}",
                matched_text=str(hit.payload.get("example_text") or hit.payload.get("text") or ""),
                reason=f"Qdrant 意图样本: {hit.payload.get('example_text') or hit.payload.get('text')}",
            )
            for hit in hits
            if hit.payload.get("intent")
        ]
