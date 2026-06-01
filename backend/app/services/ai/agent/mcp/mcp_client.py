"""可复用搜索工具的 MCP 客户端门面。"""

from __future__ import annotations

import logging

from app.services.ai.agent.types import ToolResult

logger = logging.getLogger(__name__)


async def search_knowledge(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    **kwargs,
) -> ToolResult:
    """通过 Qdrant RAG 检索知识分块和标准问答对。"""
    _ = contact_id
    query = str(kwargs.get("query") or "")
    top_k = int(kwargs.get("top_k", 5))
    db = kwargs.get("db")

    if not query.strip():
        return ToolResult(ok=True, skill_name="search_knowledge", result={"chunks": [], "qa_matches": [], "message": "查询为空"})
    if db is None:
        logger.warning("search_knowledge missing db session; cannot execute RAG search")
        return ToolResult(ok=True, skill_name="search_knowledge", result={"chunks": [], "qa_matches": [], "message": "知识库服务暂不可用"})

    from app.services.rag_service import RAGService

    result = await RAGService().search(query, tenant_id, db)
    result["chunks"] = result["chunks"][:top_k]
    result["qa_matches"] = result["qa_matches"][:max(top_k, 3)]
    logger.info(
        "search_knowledge complete: tenant_id=%s query=%s chunks=%s qa=%s",
        tenant_id,
        query[:80],
        len(result["chunks"]),
        len(result["qa_matches"]),
    )
    return ToolResult(ok=True, skill_name="search_knowledge", result=result)


async def search_images(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    **kwargs,
) -> ToolResult:
    """通过 Qdrant 检索图片元数据。

    这里还不是 CLIP 图片向量检索，只搜索文件名、标签和商品绑定等文本信息。
    这样可以先替换掉 MCP stub，同时保留后续多模态 embedding 的清晰接入点。
    """
    _ = contact_id
    query = str(kwargs.get("query") or "")
    top_k = int(kwargs.get("top_k", 5))
    db = kwargs.get("db")

    if not query.strip():
        return ToolResult(ok=True, skill_name="search_images", result={"images": [], "message": "查询为空"})
    if db is None:
        logger.warning("search_images missing db session; cannot execute image metadata search")
        return ToolResult(ok=True, skill_name="search_images", result={"images": [], "message": "图片搜索服务暂不可用"})

    from app.services.image_service import ImageService

    images = await ImageService().search_images(db, tenant_id, query, top_k=top_k)
    items = [
        {
            "id": str(image.id),
            "filename": image.filename,
            "file_url": image.file_url,
            "mime_type": image.mime_type,
            "tags": image.tags or [],
            "product_id": str(image.product_id) if image.product_id else None,
            "qdrant_point_id": image.qdrant_point_id,
        }
        for image in images
    ]
    logger.info("search_images complete: tenant_id=%s query=%s count=%s", tenant_id, query[:80], len(items))
    return ToolResult(ok=True, skill_name="search_images", result={"images": items, "count": len(items)})
