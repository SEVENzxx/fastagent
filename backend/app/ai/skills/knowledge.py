"""KnowledgeSkill — 知识检索 Skill。

只接收结构化参数，不做意图识别，不调用 LLM。
search_qa 和 search_knowledge 分别对接 QA_PAIR 和 KNOWLEDGE_CHUNK 向量域。
"""

from __future__ import annotations

import logging
from typing import Any

from app.ai.rag.vector_search import VectorDomain, VectorSearchService
from app.ai.handlers.base import ToolResult
from app.services.rag_service import RAGService

logger = logging.getLogger(__name__)


async def search_qa(
    *,
    tenant_id: int,
    query: str,
    db: Any = None,
) -> ToolResult:
    """从 QA_PAIR 向量域检索标准问答对。

    参数：
        tenant_id: 租户 ID。
        query: 检索文本。
        db: 保留参数，兼容 Handler _call_skill 签名。

    返回：
        ToolResult，result 为 {items: [{id, question, answer, score}]}。
    """
    _ = db
    try:
        matches = await RAGService().search_qa(query, tenant_id)
    except Exception:
        logger.warning("知识 QA 检索失败: tenant_id=%s query=%s", tenant_id, query[:80])
        return ToolResult(ok=False, skill_name="search_qa", error="QA 检索服务暂不可用")

    items = []
    for m in matches:
        items.append({
            "id": m.get("id", ""),
            "question": m.get("question", ""),
            "answer": m.get("answer", ""),
            "score": m.get("score", 0),
        })
    return ToolResult(ok=True, skill_name="search_qa", result={"items": items})


async def search_knowledge(
    *,
    tenant_id: int,
    query: str,
    doc_ids: list[str] | None = None,
    db: Any = None,
    top_k: int = 5,
    min_score: float = 0.65,
) -> ToolResult:
    """从 KNOWLEDGE_CHUNK 向量域检索知识分块。

    参数：
        tenant_id: 租户 ID。
        query: 检索文本。
        doc_ids: 可选，按文档 ID 过滤（追问场景缩小范围）。
        db: 保留参数，兼容 Handler _call_skill 签名。
        top_k: 最大返回数。
        min_score: 最低相似度阈值。

    返回：
        ToolResult，result 为 {items: [{id, doc_id, content, token_count, title, score}]}。
    """
    _ = db
    vs = VectorSearchService()

    filters: dict[str, Any] = {}
    if doc_ids:
        filters["doc_id"] = doc_ids

    try:
        hits = await vs.search_text(
            domain=VectorDomain.KNOWLEDGE_CHUNK,
            tenant_id=tenant_id,
            query=query,
            top_k=top_k,
            min_score=min_score,
            filters=filters if filters else None,
        )
    except Exception:
        logger.warning("知识分块检索失败: tenant_id=%s query=%s", tenant_id, query[:80])
        return ToolResult(ok=False, skill_name="search_knowledge", error="知识检索服务暂不可用")

    items = []
    for hit in hits:
        payload = hit.payload
        items.append({
            "id": str(payload.get("chunk_id") or payload.get("business_id") or hit.point_id),
            "doc_id": str(payload.get("doc_id") or ""),
            "content": str(payload.get("text") or ""),
            "token_count": payload.get("token_count"),
            "title": str(payload.get("title") or payload.get("doc_title") or ""),
            "score": hit.score,
        })
    return ToolResult(ok=True, skill_name="search_knowledge", result={"items": items})
