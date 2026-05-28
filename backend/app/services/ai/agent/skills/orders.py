"""订单类 Skill stub — Phase 10 替换为真实实现。"""

from __future__ import annotations

import logging

from app.services.ai.agent.types import ToolResult

logger = logging.getLogger(__name__)


async def create_order(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    **kwargs,
) -> ToolResult:
    """创建订单 stub — Phase 10 实现。"""
    logger.info(
        "Stub create_order 被调用：tenant_id=%s contact_id=%s",
        tenant_id,
        contact_id,
    )
    return ToolResult(
        ok=True,
        skill_name="create_order",
        result={"message": "订单创建功能即将上线，请联系人工客服协助下单。"},
    )


async def confirm_order(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    **kwargs,
) -> ToolResult:
    """确认订单 stub — Phase 10 实现。"""
    logger.info(
        "Stub confirm_order 被调用：tenant_id=%s contact_id=%s",
        tenant_id,
        contact_id,
    )
    return ToolResult(
        ok=True,
        skill_name="confirm_order",
        result={"message": "订单确认功能即将上线。"},
    )


async def manage_order(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    **kwargs,
) -> ToolResult:
    """订单管理 stub（查状态/物流/发票）— Phase 10 实现。"""
    logger.info(
        "Stub manage_order 被调用：tenant_id=%s contact_id=%s",
        tenant_id,
        contact_id,
    )
    return ToolResult(
        ok=True,
        skill_name="manage_order",
        result={"message": "订单查询功能即将上线，如需查询订单请转接人工客服。"},
    )
