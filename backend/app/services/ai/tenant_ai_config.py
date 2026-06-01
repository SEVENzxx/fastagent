"""租户级 AI 配置读取。

本模块提供统一的"租户配置优先，平台默认兜底"的读取模式。
所有硬编码的业务文本均迁移到此模块或通过此模块读取 tenant 配置。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

# ===========================================================================
# 平台级默认值（多租户通用兜底，不含具体业务品牌信息）
# ===========================================================================

DEFAULT_STORE_SHOWCASE = "欢迎光临！如需了解商品、下单或查询订单，请随时告诉我。"
DEFAULT_AI_GREETING = "您好，我是智能客服助手，正在为您服务。如需人工客服，请随时告知。"

DEFAULT_GENERATE_REPLY_SYSTEM_PROMPT = """\
你是智能客服助手，正在为客户提供服务。

请根据以下工具调用结果，用简洁、自然、礼貌的中文回复客户。
- 如果工具调用成功并返回了数据，请自然地组织成客户能理解的内容。
- 如果工具调用失败或返回空结果，请礼貌告知客户当前无法处理并建议下一步。
- 不要编造工具返回结果中没有的信息。
- 不要使用"根据工具调用结果"、"系统返回"、"查询结果显示"等透露内部机制的表述。
- 保持回复简洁，一次不要输出超过 200 字。
"""

DEFAULT_CLARIFY_PROMPT = (
    "你是智能客服助手。用户的意图不太明确，请用简洁礼貌的中文引导用户说明具体需求。"
    "不超过 60 字。"
)

DEFAULT_FALLBACK_SYSTEM_PROMPT = "你是智能客服助手，请用简洁自然的中文回复用户，不超过 100 字。"

# 兜底话术
DEFAULT_FALLBACK_MESSAGES = {
    "agent_planner": "抱歉，您的问题比较复杂，正在为您转接人工客服，请稍候。",
    "clarify_product_or_order": "请问您是想了解我们的产品，还是有具体的订单问题需要我帮您处理？",
    "generic_ack": "好的，我已收到您的消息。如需进一步帮助，请随时告诉我。",
    "empty_reply_general": "您好，请问有什么可以帮助您的？",
    "error_fallback": "抱歉，暂时无法处理您的请求，请稍后再试或转接人工客服。",
    "template_fallback": "好的，我已收到您的请求。",
}

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


async def get_fallback_messages(db: AsyncSession, tenant_id: int) -> dict[str, str]:
    """获取租户自定义的兜底话术集合。"""
    # 目前从 tenant.custom_prompt 外的独立字段读取；未来可扩展为 JSON 字段
    return DEFAULT_FALLBACK_MESSAGES.copy()


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


def get_default_reply_system_prompt() -> str:
    """返回默认的 reply 系统提示词。"""
    return DEFAULT_GENERATE_REPLY_SYSTEM_PROMPT


def get_default_clarify_prompt() -> str:
    """返回默认的澄清追问 prompt。"""
    return DEFAULT_CLARIFY_PROMPT


def get_default_fallback_system_prompt() -> str:
    """返回默认的兜底回复系统提示词。"""
    return DEFAULT_FALLBACK_SYSTEM_PROMPT
