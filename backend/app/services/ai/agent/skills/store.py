"""get_store_showcase — 品牌/店铺介绍（真实实现，无 DB 依赖）。"""

from __future__ import annotations

import logging

from app.services.ai.agent.types import ToolResult

logger = logging.getLogger(__name__)


async def get_store_showcase(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    **kwargs,
) -> ToolResult:
    """返回店铺品牌介绍。"""
    logger.info(
        "Skill get_store_showcase 被调用：tenant_id=%s contact_id=%s",
        tenant_id,
        contact_id,
    )
    showcase = (
        "【FastAgent 智能茶庄】\n"
        "我们是一家专注高品质茶叶的精选茶庄，主营：\n"
        "  - 绿茶：龙井、碧螺春、毛尖\n"
        "  - 红茶：正山小种、金骏眉、祁门红茶\n"
        "  - 乌龙茶：铁观音、大红袍、凤凰单丛\n"
        "  - 普洱茶：生普、熟普、古树茶\n"
        "  - 花茶：茉莉花茶、桂花龙井\n"
        "所有茶叶均来自原产地直采，品质有保障。支持全国快递配送。"
    )
    return ToolResult(ok=True, skill_name="get_store_showcase", result=showcase)
