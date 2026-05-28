"""运营类 Skill stub — Phase 12 替换为真实实现。"""

from __future__ import annotations

import logging

from app.services.ai.agent.types import ToolResult

logger = logging.getLogger(__name__)


async def update_price_strategy(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    **kwargs,
) -> ToolResult:
    """定价策略更新 stub — Phase 12 实现。"""
    logger.info(
        "Stub update_price_strategy 被调用：tenant_id=%s",
        tenant_id,
    )
    return ToolResult(
        ok=True,
        skill_name="update_price_strategy",
        result={"message": "定价策略管理功能即将上线。"},
    )


async def list_documents(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    **kwargs,
) -> ToolResult:
    """营销文档查询 stub — Phase 12 实现。"""
    logger.info(
        "Stub list_documents 被调用：tenant_id=%s",
        tenant_id,
    )
    return ToolResult(
        ok=True,
        skill_name="list_documents",
        result={"documents": [], "message": "营销文档功能即将上线。"},
    )


async def manage_todos(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    **kwargs,
) -> ToolResult:
    """会话待办管理 stub — Phase 12 实现。"""
    logger.info(
        "Stub manage_todos 被调用：tenant_id=%s",
        tenant_id,
    )
    return ToolResult(
        ok=True,
        skill_name="manage_todos",
        result={"todos": [], "message": "待办管理功能即将上线。"},
    )
