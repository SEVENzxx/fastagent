"""订单 Schema — Phase 10"""

from datetime import datetime

from pydantic import field_serializer, field_validator

from app.schemas.base import CamelModel

# ---------------------------------------------------------------------------
# 状态流转规则
# ---------------------------------------------------------------------------

STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"pending_customer_confirm", "cancelled"},
    "pending_customer_confirm": {"customer_confirmed", "cancelled"},
    "customer_confirmed": {"agent_confirmed", "cancelled"},
    "agent_confirmed": {"shipped", "cancelled"},
    "shipped": {"signed"},
    "signed": set(),
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

    product_name: str
    quantity: int = 1

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("数量必须 >= 1")
        return v


class OrderItemUpdate(CamelModel):
    """更新订单明细"""

    product_name: str | None = None
    quantity: int | None = None
    unit_price: float | None = None

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("数量必须 >= 1")
        return v


class OrderItemResponse(CamelModel):
    """订单明细响应"""

    id: int
    order_id: int
    product_id: int | None = None
    product_snapshot: dict | None = None
    quantity: int
    unit_price: float
    subtotal: float
    created_at: datetime

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

    contact_id: int | None = None
    conversation_id: int | None = None
    items: list[OrderItemCreate]
    shipping_address: str | None = None
    receiver_name: str | None = None
    receiver_phone: str | None = None
    remark: str | None = None
    status: str = "pending_customer_confirm"

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

    shipping_address: str | None = None
    receiver_name: str | None = None
    receiver_phone: str | None = None
    remark: str | None = None
    discount_amount: float | None = None
    add_items: list[OrderItemCreate] | None = None
    remove_item_ids: list[int] | None = None
    update_items: list[OrderItemUpdate] | None = None


class OrderStatusTransition(CamelModel):
    """订单状态变更"""

    status: str

    @field_validator("status")
    @classmethod
    def status_valid(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"无效状态: {v}")
        return v


class OrderBatchStatusTransition(CamelModel):
    """批量状态变更"""

    order_ids: list[int]
    status: str

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

    id: int
    tenant_id: int
    contact_id: int
    conversation_id: int | None = None
    employee_id: int | None = None
    status: str
    total_amount: float
    discount_amount: float
    payable_amount: float
    shipping_address: str | None = None
    receiver_name: str | None = None
    receiver_phone: str | None = None
    remark: str | None = None
    metadata_: dict | None = None
    created_by_type: str
    created_by_employee_id: int | None = None
    confirmed_at: datetime | None = None
    shipped_at: datetime | None = None
    signed_at: datetime | None = None
    cancelled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse] = []
    contact_name: str | None = None

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

    items: list[OrderResponse]
    total: int
    page: int
    page_size: int
