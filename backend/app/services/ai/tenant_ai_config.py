"""租户级 AI 配置读取。

本模块负责读取租户级 AI 配置。Prompt 模板统一存放在 services/ai/prompts。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant

# ===========================================================================
# 平台级默认值（多租户通用兜底，不含具体业务品牌信息）
# ===========================================================================

DEFAULT_STORE_SHOWCASE = "欢迎光临！如需了解商品、下单或查询订单，请随时告诉我。"
DEFAULT_AI_GREETING = "您好，我是智能客服助手，正在为您服务。如需人工客服，请随时告知。"

# 寒暄短句过滤
DEFAULT_IGNORE_PHRASES: set[str] = {"你好", "您好", "谢谢", "再见"}

# 订单状态标签（多租户通用）
DEFAULT_ORDER_STATUS_LABELS: dict[str, str] = {
    "draft": "草稿",
    "pending_customer_confirm": "待客户确认",
    "customer_confirmed": "客户已确认",
    "agent_confirmed": "已确认",
    "shipped": "已发货",
    "signed": "已签收",
    "cancelled": "已取消",
}

# 客户信息字段标签
DEFAULT_FIELD_LABELS: dict[str, str] = {
    "address": "收货地址",
    "phone": "联系电话",
}

# 通用数量单位（匹配中文量词）
DEFAULT_QUANTITY_UNITS = "个件瓶盒箱份套台本张卷支块包袋桶罐"


# ===========================================================================
# 租户配置读取
# ===========================================================================


async def get_tenant(db: AsyncSession, tenant_id: int) -> Tenant | None:
    """读取租户记录，带缓存后续可加 Redis。"""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    return result.scalar_one_or_none()


async def get_store_showcase(db: AsyncSession, tenant_id: int) -> str:
    """获取租户的品牌/店铺介绍。"""
    tenant = await get_tenant(db, tenant_id)
    if tenant is not None and tenant.store_showcase:
        return tenant.store_showcase
    return DEFAULT_STORE_SHOWCASE


async def get_ai_greeting(db: AsyncSession, tenant_id: int) -> str:
    """获取租户的 AI 首次问候语。"""
    tenant = await get_tenant(db, tenant_id)
    if tenant is not None and tenant.ai_greeting_message:
        return tenant.ai_greeting_message
    return DEFAULT_AI_GREETING


async def get_custom_prompt(db: AsyncSession, tenant_id: int) -> str | None:
    """读取租户的 custom_prompt（AI 人设），可覆盖系统默认提示词。"""
    tenant = await get_tenant(db, tenant_id)
    if tenant is not None and tenant.custom_prompt:
        return tenant.custom_prompt
    return None


# ===========================================================================
# 非 DB 配置（代码内可替换默认值）
# ===========================================================================


def get_intent_route_map(**overrides: Any) -> dict:
    """返回意图路由映射（支持租户级覆盖）。

    当前返回平台默认配置，未来从 DB 的 tenant_intent_config 表读取。
    """
    from app.services.ai.config.intent_config import DEFAULT_INTENT_ROUTE_MAP
    return DEFAULT_INTENT_ROUTE_MAP


def get_strong_rules(**overrides: Any) -> tuple:
    """返回强规则配置。"""
    from app.services.ai.config.intent_config import DEFAULT_RULES
    return DEFAULT_RULES


def get_keyword_boosts(**overrides: Any) -> tuple:
    """返回关键词加权配置。"""
    from app.services.ai.config.intent_config import DEFAULT_KEYWORD_BOOSTS
    return DEFAULT_KEYWORD_BOOSTS


def get_order_status_labels(**overrides: Any) -> dict[str, str]:
    """返回订单状态中文标签。"""
    return {**DEFAULT_ORDER_STATUS_LABELS, **overrides}


def get_field_labels(**overrides: Any) -> dict[str, str]:
    """返回客户信息字段中文标签。"""
    return {**DEFAULT_FIELD_LABELS, **overrides}


def get_ignore_phrases(**overrides: Any) -> set[str]:
    """返回寒暄短句过滤集。"""
    return DEFAULT_IGNORE_PHRASES | set(overrides.get("extra", []))
