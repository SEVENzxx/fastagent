"""技能参数合约定义 + 字段抽取器注册表。

架构原则：
  - SkillSpec 定义"技能需要什么参数"（what）+ "从文本中怎么抽"（how）
  - 字段级抽取器（FieldExtractor）适用于大多数简单技能
  - 复合抽取器（CompositeExtractor）适用于字段间有依赖关系的复杂技能
  - 新增技能只需在 EXTRACTOR_REGISTRY 加一行注册，无需修改分发逻辑

企业级设计参考：Spring HandlerMapping / Django REST ViewSet 路由注册表。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Union

from pydantic import Field

from app.ai.schemas.base import SkillArgs
from app.ai.schemas.order import (
    ConfirmOrderArgs,
    CreateOrderArgs,
    ManageOrderArgs,
    UpdateDraftOrderQuantityArgs,
    UpdateOrderDraftArgs,
)

# 风险等级：读 / 写 / 写前确认 / 需人工审批
RiskLevel = Literal["read", "write", "write_confirm", "human_approval"]


# ── 抽取器类型定义 ──
# 字段抽取器：从客户文本中提取单个字段值     extract(text: str) -> Any | None
FieldExtractor = Callable[[str], Any | None]
# 复合抽取器：处理字段间有关联的复杂抽取   extract(args: dict, text: str) -> dict
CompositeExtractor = Callable[[dict[str, Any], str], dict[str, Any]]
# 跨轮参数合并函数：合并上一轮 pending 的参数          merge(current: dict, pending: dict) -> dict
MergeFunc = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
# 业务数据解析函数：将自然语言参数解析为具体的业务记录    resolve(plan: dict, db, tenant_id) -> dict
BusinessResolver = Callable[[dict[str, Any], "AsyncSession", int], Awaitable[dict[str, Any]]]


# ── 各技能参数模型 ──

class StoreShowcaseArgs(SkillArgs):
    """店铺橱窗：展示店铺热门商品。"""
    query: str | None = None
    customer_text: str | None = None


class SearchProductsArgs(SkillArgs):
    """商品搜索：按关键词或模糊语义搜索商品。"""
    query: str | None = None
    keyword: str | None = None
    category: str | None = None
    product_name: str | None = None
    customer_text: str | None = None


class RememberInfoArgs(SkillArgs):
    """客户偏好记忆：记录客户备注或偏好信息。"""
    customer_text: str = Field(default="")


class UpdatePriceStrategyArgs(SkillArgs):
    """更新报价策略：记录客户报价信息。"""
    query: str | None = None
    customer_text: str | None = None
    product_id: int | None = None
    product_name: str | None = None
    quoted_price: float | None = Field(default=None, gt=0)


class ListDocumentsArgs(SkillArgs):
    """文档列表：查询租户文档。"""
    query: str | None = None
    keyword: str | None = None
    customer_text: str | None = None


class ManageTodosArgs(SkillArgs):
    """待办管理：坐席待办项的增删查。"""
    query: str | None = None
    customer_text: str | None = None
    action: str = "list"
    conversation_id: int | None = None
    todo_id: int | None = None
    content: str | None = None
    due_at: str | None = None


# ── 技能规格（SkillSpec）──

@dataclass(frozen=True, slots=True)
class SkillSpec:
    """技能规格：参数模型 + 必填项 + 风险等级 + 追问话术。

    Attributes
    ----------
    name : 技能名称（与 SKILL_REGISTRY key 一致）
    args_model : 参数 Pydantic 模型类
    required_args : 执行前必须提供的参数名称元组
    risk_level : 读 / 写 / 写前确认 / 需人工审批
    missing_prompts : 缺参追问话术，key 为参数名
    """
    name: str
    args_model: type[SkillArgs]
    required_args: tuple[str, ...] = ()
    risk_level: RiskLevel = "read"
    missing_prompts: dict[str, str] = field(default_factory=dict)


# 技能规格注册表：{skill_name: SkillSpec}
SKILL_SPECS: dict[str, SkillSpec] = {
    "get_store_showcase": SkillSpec(
        name="get_store_showcase",
        args_model=StoreShowcaseArgs,
        risk_level="read",
    ),
    "list_product_categories": SkillSpec(
        name="list_product_categories",
        args_model=StoreShowcaseArgs,
        risk_level="read",
    ),
    "search_products": SkillSpec(
        name="search_products",
        args_model=SearchProductsArgs,
        risk_level="read",
    ),
    "get_product_detail": SkillSpec(
        name="get_product_detail",
        args_model=SearchProductsArgs,
        risk_level="read",
    ),
    "remember_info": SkillSpec(
        name="remember_info",
        args_model=RememberInfoArgs,
        required_args=("customer_text",),
        risk_level="write",
        missing_prompts={"customer_text": "请告诉我需要记录的客户偏好或备注。"},
    ),
    "create_order": SkillSpec(
        name="create_order",
        args_model=CreateOrderArgs,
        required_args=("items",),
        risk_level="write_confirm",  # 下单操作需二次确认
        missing_prompts={"items": "请告诉我要下单的商品和数量。"},
    ),
    "create_order_draft": SkillSpec(
        name="create_order_draft",
        args_model=CreateOrderArgs,
        required_args=("items",),
        risk_level="write_confirm",
        missing_prompts={"items": "请告诉我要下单的商品和数量。"},
    ),
    "update_order_draft": SkillSpec(
        name="update_order_draft",
        args_model=UpdateOrderDraftArgs,
        required_args=("order_id",),
        risk_level="write_confirm",
        missing_prompts={"order_id": "请提供要修改的订单号。"},
    ),
    "update_draft_order_quantity": SkillSpec(
        name="update_draft_order_quantity",
        args_model=UpdateDraftOrderQuantityArgs,
        risk_level="write_confirm",
    ),
    "confirm_order": SkillSpec(
        name="confirm_order",
        args_model=ConfirmOrderArgs,
        required_args=("order_id",),
        risk_level="write_confirm",
        missing_prompts={"order_id": "请提供要确认的订单号。"},
    ),
    "manage_order": SkillSpec(
        name="manage_order",
        args_model=ManageOrderArgs,
        risk_level="read",
    ),
    "update_price_strategy": SkillSpec(
        name="update_price_strategy",
        args_model=UpdatePriceStrategyArgs,
        required_args=("quoted_price", "product_name"),
        risk_level="human_approval",  # 报价修改需人工审批
        missing_prompts={"quoted_price": "请提供客户本次报价金额。"},
    ),
    "list_documents": SkillSpec(
        name="list_documents",
        args_model=ListDocumentsArgs,
        risk_level="read",
    ),
    "manage_todos": SkillSpec(
        name="manage_todos",
        args_model=ManageTodosArgs,
        risk_level="write",
    ),
}


def get_skill_spec(skill_name: str) -> SkillSpec | None:
    """获取指定技能的规格描述，不存在则返回 None。"""
    return SKILL_SPECS.get(skill_name)


# ── 字段抽取器注册表（由 argument_extractor.py 在模块加载时填充）──
#
# 设计意图：
#   抽取函数定义在 argument_extractor.py（避免循环引用），
#   SKILL_SPECS 定义"需要什么参数"，EXTRACTOR_REGISTRY 定义"怎么从文本里抽"。
#   两者通过统一的 skill_name 关联，新增技能只需在这两个地方各加一行。
#
# 使用方式（详见 argument_extractor._extract_by_skill）：
#   - 简单字段:  field_name → extract(text) -> Any | None
#   - 复合抽取:  "__composite__" → extract(args, text) -> dict
EXTRACTOR_REGISTRY: dict[str, dict[str, Union[FieldExtractor, CompositeExtractor]]] = {}


# ── 跨轮参数合并函数注册表（由 argument_pending.py 在模块加载时填充）──
#
# 每个技能注册一个 merge(current_args, pending_args) -> dict 函数。
# 未注册的技能使用默认合并：{**pending_args, **current_args}（标量覆盖）。
# 注册复杂合并（如 create_order 的 items 列表合并）时，在此加一行。
MERGE_REGISTRY: dict[str, MergeFunc] = {}


# ── 业务数据解析注册表（由 business_resolver.py 在模块加载时填充）──
#
# 每个技能注册一个 resolver(plan, db, tenant_id) -> updated_plan 函数。
# 未注册的技能不做业务解析，直接返回原始 plan。
# 注册业务解析（如 create_order 的商品名→product_id 解析）时，在此加一行。
BUSINESS_RESOLVERS: dict[str, BusinessResolver] = {}
