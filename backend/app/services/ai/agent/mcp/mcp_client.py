"""MCP Client 抽象 + search_knowledge / search_images stub。

Phase 11 替换为真实 MCP 调用（pgvector RAG）。
"""

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
    """知识检索 MCP stub — Phase 11 替换为 pgvector RAG。"""
    query = str(kwargs.get("query") or "")
    logger.info(
        "MCP stub search_knowledge 被调用：tenant_id=%s query=%s",
        tenant_id,
        query,
    )
    return ToolResult(
        ok=True,
        skill_name="search_knowledge",
        result={
            "chunks": [],
            "message": "知识库检索功能即将上线。",
        },
    )


async def search_images(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    **kwargs,
) -> ToolResult:
    """图片搜索 MCP stub — 延后实现。"""
    query = str(kwargs.get("query") or "")
    logger.info(
        "MCP stub search_images 被调用：tenant_id=%s query=%s",
        tenant_id,
        query,
    )
    return ToolResult(
        ok=True,
        skill_name="search_images",
        result={
            "images": [],
            "message": "图片搜索功能暂未开放。",
        },
    )
