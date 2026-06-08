"""技能注册表 + 意图别名映射。

流水线：intent.skill → SKILL_ALIASES 解析 → SKILL_REGISTRY key → 实际函数。
通过别名映射解耦意图名称和技能实现名称，支持多个 intent.skill 聚合到一个 skill。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.ai.skills.memory import remember_info
from app.ai.skills.operations import list_documents, manage_todos, update_price_strategy
from app.ai.skills.orders import cancel_order_draft, confirm_order, create_order, create_order_draft, manage_order, update_order_draft
from app.ai.skills.products import get_product_detail, list_product_categories, search_products
from app.ai.skills.store import get_store_showcase

logger = logging.getLogger(__name__)

# 技能注册表：{registry_key: 异步技能函数}
SKILL_REGISTRY: dict[str, Callable[..., Any]] = {
    "get_store_showcase": get_store_showcase,
    "list_product_categories": list_product_categories,
    "search_products": search_products,
    "get_product_detail": get_product_detail,
    "remember_info": remember_info,
    "create_order": create_order,
    "create_order_draft": create_order_draft,
    "update_order_draft": update_order_draft,
    "cancel_order_draft": cancel_order_draft,
    "confirm_order": confirm_order,
    "manage_order": manage_order,
    "update_price_strategy": update_price_strategy,
    "list_documents": list_documents,
    "manage_todos": manage_todos,
}

# intent.skill → registry key 映射（平台默认，租户可通过 DB 覆盖）
# 多个意图（product_search、product_price 等）聚合到同一个 search_products 技能
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
    "discount_request": "update_price_strategy",
    "save_preference": "remember_info",
    # None 表示该意图需人工处理，不进入技能调用
    "human_service": None,
}


def resolve_skill(intent_skill: str | None) -> str | None:
    """从 intent.skill 解析为 registry key。

    流程：intent_skill → 查 SKILL_ALIASES → 得到 alias → 校验 alias 在 SKILL_REGISTRY 中。
    若 intent_skill 为空或 alias 为 None 或不在注册表中，返回 None。
    """
    if not intent_skill:
        return None
    alias = SKILL_ALIASES.get(intent_skill, intent_skill)
    if alias is not None and alias not in SKILL_REGISTRY:
        logger.warning("Skill alias 解析后不在 registry 中：intent_skill=%s alias=%s", intent_skill, alias)
        return None
    return alias
