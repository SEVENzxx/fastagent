"""订单 Schema — Phase 10"""

from datetime import datetime

from pydantic import Field, field_serializer, field_validator

from app.schemas.base import CamelModel

# ---------------------------------------------------------------------------
# 状态流转规则
# ---------------------------------------------------------------------------

STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"pending_customer_confirm", "cancelled"},
    "pending_customer_confirm": {"customer_confirmed", "paid", "cancelled"},
    "paid": {"agent_confirmed", "cancelled"},
    "customer_confirmed": {"agent_confirmed", "cancelled"},
    "agent_confirmed": {"shipped", "cancelled"},
    "shipped": {"signed", "refunding"},
    "signed": {"refunding"},
    "refunding": {"refunded"},
    "refunded": set(),
    "cancelled": set(),
}

VALID_STATUSES = frozenset(STATUS_TRANSITIONS.keys())


def can_transition(from_status: str, to_status: str) -> bool:
    return to_status in STATUS_TRANSITIONS.get(from_status, set())


# ---------------------------------------------------------------------------
# OrderItem schemas
# ---------------------------------------------------------------------------


class OrderItemCreate(CamelModel):
    """创建订单明细"""

    product_name: str = Field(description="商品名称")
    quantity: int = Field(1, description="数量")

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("数量必须 >= 1")
        return v


class OrderItemUpdate(CamelModel):
    """更新订单明细"""

    product_name: str | None = Field(None, description="商品名称")
    quantity: int | None = Field(None, description="数量")
    unit_price: float | None = Field(None, description="单价")

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("数量必须 >= 1")
        return v


class OrderItemResponse(CamelModel):
    """订单明细响应"""

    id: int = Field(description="明细 ID")
    order_id: int = Field(description="订单 ID")
    product_id: int | None = Field(None, description="商品 ID")
    product_snapshot: dict | None = Field(None, description="下单时商品快照")
    quantity: int = Field(description="数量")
    unit_price: float = Field(description="单价")
    subtotal: float = Field(description="小计金额")
    created_at: datetime = Field(description="创建时间")

    @field_serializer("id", "order_id", "product_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)


# ---------------------------------------------------------------------------
# Order schemas
# ---------------------------------------------------------------------------


class OrderCreate(CamelModel):
    """创建订单"""

    contact_id: int | None = Field(None, description="客户联系人 ID")
    conversation_id: int | None = Field(None, description="会话 ID")
    items: list[OrderItemCreate] = Field(description="订单商品明细")
    shipping_address: str | None = Field(None, description="收货地址")
    receiver_name: str | None = Field(None, description="收货人姓名")
    receiver_phone: str | None = Field(None, description="收货人电话")
    remark: str | None = Field(None, description="备注")
    status: str = Field("pending_customer_confirm", description="初始状态")

    @field_validator("items")
    @classmethod
    def items_not_empty(cls, v: list[OrderItemCreate]) -> list[OrderItemCreate]:
        if not v:
            raise ValueError("订单必须包含至少一个商品")
        return v

    @field_validator("status")
    @classmethod
    def status_valid(cls, v: str) -> str:
        if v not in {"draft", "pending_customer_confirm"}:
            raise ValueError("创建时状态只能为 draft 或 pending_customer_confirm")
        return v


class OrderUpdate(CamelModel):
    """修改订单"""

    shipping_address: str | None = Field(None, description="收货地址")
    receiver_name: str | None = Field(None, description="收货人姓名")
    receiver_phone: str | None = Field(None, description="收货人电话")
    remark: str | None = Field(None, description="备注")
    discount_amount: float | None = Field(None, description="优惠金额")
    add_items: list[OrderItemCreate] | None = Field(None, description="新增商品明细")
    remove_item_ids: list[int] | None = Field(None, description="待删除的明细 ID 列表")
    update_items: list[OrderItemUpdate] | None = Field(None, description="待更新的明细列表")


class OrderStatusTransition(CamelModel):
    """订单状态变更"""

    status: str = Field(description="目标状态")

    @field_validator("status")
    @classmethod
    def status_valid(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"无效状态: {v}")
        return v


class OrderBatchStatusTransition(CamelModel):
    """批量状态变更"""

    order_ids: list[int] = Field(description="要变更的订单 ID 列表")
    status: str = Field(description="目标状态")

    @field_validator("order_ids")
    @classmethod
    def ids_not_empty(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("必须指定至少一个订单")
        return v

    @field_validator("status")
    @classmethod
    def status_valid(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"无效状态: {v}")
        return v


class OrderResponse(CamelModel):
    """订单响应"""

    id: int = Field(description="订单 ID")
    tenant_id: int = Field(description="租户 ID")
    contact_id: int = Field(description="客户联系人 ID")
    conversation_id: int | None = Field(None, description="关联会话 ID")
    employee_id: int | None = Field(None, description="处理坐席 ID")
    status: str = Field(description="订单状态")
    total_amount: float = Field(description="订单总金额")
    discount_amount: float = Field(description="优惠金额")
    payable_amount: float = Field(description="应付金额")
    shipping_address: str | None = Field(None, description="收货地址")
    receiver_name: str | None = Field(None, description="收货人姓名")
    receiver_phone: str | None = Field(None, description="收货人电话")
    remark: str | None = Field(None, description="备注")
    metadata_: dict | None = Field(None, description="扩展元数据")
    created_by_type: str = Field(description="创建者类型（contact/employee）")
    created_by_employee_id: int | None = Field(None, description="创建坐席 ID")
    confirmed_at: datetime | None = Field(None, description="确认时间")
    shipped_at: datetime | None = Field(None, description="发货时间")
    signed_at: datetime | None = Field(None, description="签收时间")
    cancelled_at: datetime | None = Field(None, description="取消时间")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")
    items: list[OrderItemResponse] = Field(default_factory=list, description="订单明细列表")
    contact_name: str | None = Field(None, description="客户名称")

    @field_serializer(
        "id", "tenant_id", "contact_id", "conversation_id",
        "employee_id", "created_by_employee_id",
    )
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)


class OrderListResponse(CamelModel):
    """订单列表响应"""

    items: list[OrderResponse] = Field(description="订单列表")
    total: int = Field(description="总数")
    page: int = Field(description="当前页码")
    page_size: int = Field(description="每页条数")
