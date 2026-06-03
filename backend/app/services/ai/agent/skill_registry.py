"""Skill Registry + Skill Alias + MCP Tool Names。

Phase 8 intent.skill → SKILL_ALIASES → SKILL_REGISTRY key → 实际函数。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.services.ai.agent.mcp.mcp_client import search_images, search_knowledge
from app.services.ai.agent.skills.memory import remember_info
from app.services.ai.agent.skills.operations import list_documents, manage_todos, update_price_strategy
from app.services.ai.agent.skills.orders import confirm_order, create_order, manage_order
from app.services.ai.agent.skills.products import search_products
from app.services.ai.agent.skills.store import get_store_showcase

logger = logging.getLogger(__name__)

SKILL_REGISTRY: dict[str, Callable[..., Any]] = {
    # 真实 Skill（Phase 9 第一阶段）
    "get_store_showcase": get_store_showcase,
    "search_products": search_products,
    "remember_info": remember_info,
    # Stub Skill（Phase 10/12 替换）
    "create_order": create_order,
    "confirm_order": confirm_order,
    "manage_order": manage_order,
    "update_price_strategy": update_price_strategy,
    "list_documents": list_documents,
    "manage_todos": manage_todos,
    # MCP Stub（Phase 11 替换）
    "search_knowledge": search_knowledge,
    "search_images": search_images,
}

# Phase 8 intent.skill → Phase 9 registry key 映射（平台默认，租户可通过 DB 覆盖）
SKILL_ALIASES: dict[str, str | None] = {
    # 聚合映射：多个 intent.skill 合并到一个 registry key
    "product_search": "search_products",
    "product_inquiry": "search_products",
    "product_price": "search_products",
    "product_stock": "search_products",
    "delivery_time": "search_products",
    "order_status": "manage_order",
    "logistics_status": "manage_order",
    "invoice": "manage_order",
    # 人工路由（不进入 skill 调用）
    "human_service": None,
}

# 副作用操作（create/update/delete），进入 DIRECT_SKILL 时标记 requires_approval
SIDEEFFECT_SKILLS: set[str] = {"create_order", "confirm_order", "manage_order", "update_price_strategy"}


def resolve_skill(intent_skill: str | None) -> str | None:
    """从 Phase 8 intent.skill 解析为 registry key。"""
    if not intent_skill:
        return None
    alias = SKILL_ALIASES.get(intent_skill, intent_skill)
    if alias is not None and alias not in SKILL_REGISTRY:
        logger.warning("Skill alias 解析后不在 registry 中：intent_skill=%s alias=%s", intent_skill, alias)
        return None
    return alias
