"""订单相关 AI 工具参数 Schema。

这里定义 AI 技能接收的参数结构；HTTP API 的 DTO 仍然放在 app.schemas.order。
"""

from __future__ import annotations

from pydantic import Field

from app.ai.schemas.base import SkillArgs


class OrderItemArg(SkillArgs):
    """从客户文本中识别出的订单商品项。"""

    product_id: int | None = None
    product_name: str
    quantity: int = Field(default=1, ge=1)


class CreateOrderArgs(SkillArgs):
    """创建订单或订单草稿所需参数。"""

    query: str | None = None
    customer_text: str | None = None
    items: list[OrderItemArg] = Field(default_factory=list)
    shipping_address: str | None = None
    receiver_name: str | None = None
    receiver_phone: str | None = None
    remark: str | None = None


class UpdateOrderDraftArgs(SkillArgs):
    """更新订单草稿基础字段和首个商品项的参数。"""

    query: str | None = None
    customer_text: str | None = None
    order_id: int
    shipping_address: str | None = None
    receiver_phone: str | None = None
    receiver_name: str | None = None
    quantity: int | None = Field(default=None, ge=1)
    product_name: str | None = None


class UpdateDraftOrderQuantityArgs(SkillArgs):
    """修改订单草稿商品数量的参数。"""

    query: str | None = None
    customer_text: str | None = None
    order_id: int | None = None
    quantity: int | None = Field(default=None, ge=1)
    quantity_delta: int | None = None
    product_name: str | None = None


class ConfirmOrderArgs(SkillArgs):
    """客户确认订单的参数。"""

    query: str | None = None
    customer_text: str | None = None
    order_id: int | None = None


class ManageOrderArgs(SkillArgs):
    """订单查询和轻量订单管理的参数。"""

    query: str | None = None
    customer_text: str | None = None
    action: str = "query"
    order_id: int | None = None
