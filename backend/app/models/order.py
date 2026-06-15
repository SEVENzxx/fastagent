"""订单模型。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.utils.id_generator import generate_id


class Order(Base):
    """订单主表 —— 状态机: draft → pending_customer_confirm → customer_confirmed → agent_confirmed → shipped → signed / cancelled"""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, comment="租户ID")
    contact_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("contacts.id"), nullable=False, comment="下单客户")
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("conversations.id"), nullable=True, comment="来源会话")
    employee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("employees.id"), nullable=True, comment="负责坐席")
    status: Mapped[str] = mapped_column(String(30), default="draft", server_default="draft", comment="draft / pending_customer_confirm / customer_confirmed / agent_confirmed / shipped / signed / cancelled")
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0, server_default="0", comment="商品合计")
    discount_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0, server_default="0", comment="优惠金额")
    payable_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0, server_default="0", comment="应付金额")
    shipping_address: Mapped[str | None] = mapped_column(Text, nullable=True, comment="收货地址")
    receiver_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="收货人")
    receiver_phone: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="收货电话")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True, comment="扩展信息")
    created_by_type: Mapped[str] = mapped_column(String(20), default="agent", server_default="agent", comment="创建来源: ai / agent / system")
    created_by_employee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("employees.id"), nullable=True, comment="创建人")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="客户确认时间")
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="发货时间")
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="签收时间")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="取消时间")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # ── 关联 ──
    items: Mapped[list["OrderItem"]] = relationship("OrderItem", back_populates="order", lazy="selectin")
    contact: Mapped["Contact | None"] = relationship("Contact")

    __table_args__ = (
        Index("idx_orders_tenant_status", "tenant_id", "status"),
        Index("idx_orders_tenant_contact", "tenant_id", "contact_id", "created_at"),
        Index("idx_orders_conversation", "conversation_id"),
        {"comment": "订单主表"},
    )


class OrderItem(Base):
    """订单明细"""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, comment="订单ID")
    product_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=True, comment="商品ID（删除后保留快照）")
    product_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="商品快照：name/sku/specs/price/floor_price")
    quantity: Mapped[int] = mapped_column(Integer, default=1, server_default="1", comment="数量")
    unit_price: Mapped[float] = mapped_column(Numeric(10, 2), default=0, server_default="0", comment="成交单价")
    subtotal: Mapped[float] = mapped_column(Numeric(12, 2), default=0, server_default="0", comment="小计")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")

    order: Mapped["Order"] = relationship("Order", back_populates="items")

    __table_args__ = (
        Index("idx_order_items_order", "order_id"),
        Index("idx_order_items_product", "product_id"),
        {"comment": "订单明细表"},
    )
