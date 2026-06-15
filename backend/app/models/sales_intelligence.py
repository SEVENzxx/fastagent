"""销售智能模型 —— 客户 360 视图、销售管线、跟进计划和会话待办。

与订单和消息表分开存储：销售上下文是持续更新的"当前状态"，而非不可变的业务事实。
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils.id_generator import generate_id


class SalesContext(Base):
    """客户级销售上下文 —— 每个租户下每个客户仅保留一条当前快照。"""

    __tablename__ = "sales_contexts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, comment="所属租户")
    contact_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("contacts.id"), nullable=False, comment="关联客户（1:1）")
    stage: Mapped[str] = mapped_column(String(30), nullable=False, default="new", server_default="new", comment="销售阶段: new / contacting / negotiating / closed_won / retention / closed_lost")
    pricing_level: Mapped[str] = mapped_column(String(30), nullable=False, default="normal", server_default="normal", comment="定价级别: normal / vip / wholesale")
    followup_state: Mapped[str] = mapped_column(String(30), nullable=False, default="none", server_default="none", comment="跟进状态: none / scheduled / executing / cooling / unsubscribed")
    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="下次跟进时间")
    last_interaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="最近互动时间")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="AI 生成的客户需求摘要")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")

    __table_args__ = (
        Index("idx_sales_ctx_contact", "tenant_id", "contact_id", unique=True),
        Index("idx_sales_ctx_followup", "tenant_id", "next_followup_at"),
        {"comment": "客户级销售上下文"},
    )


class ContactProductContext(Base):
    """客户与商品之间的销售管线上下文 —— 记录最近报价和谈判阶段。"""

    __tablename__ = "contact_product_contexts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, comment="所属租户")
    contact_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("contacts.id"), nullable=False, comment="关联客户")
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False, comment="关联商品")
    stage: Mapped[str] = mapped_column(String(30), nullable=False, default="inquiry", server_default="inquiry", comment="销售阶段: inquiry / quoted / negotiating / accepted / rejected")
    quoted_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True, comment="最近报价金额")
    price_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1", comment="报价级别（1-N）")
    order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("orders.id"), nullable=True, comment="成交后关联订单ID")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="最后更新时间")

    __table_args__ = (
        Index("idx_cpc_contact_product", "tenant_id", "contact_id", "product_id", unique=True),
        Index("idx_cpc_order", "order_id"),
        {"comment": "客户与商品销售管线上下文"},
    )


class FollowupPlan(Base):
    """客户跟进计划 —— AI Agent 或人工坐席创建的定时跟进任务。"""

    __tablename__ = "followup_plans"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, comment="所属租户")
    contact_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("contacts.id"), nullable=False, comment="目标客户")
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("conversations.id"), nullable=True, comment="关联会话ID")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="发送消息内容")
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="计划发送时间")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending", comment="执行状态: pending / sent / failed / cancelled / cooling")
    created_by_type: Mapped[str] = mapped_column(String(20), nullable=False, default="agent", server_default="agent", comment="创建来源: agent / human")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="失败原因")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="实际发送时间")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")

    __table_args__ = (
        Index("idx_followup_tenant_status_time", "tenant_id", "status", "scheduled_at"),
        Index("idx_followup_contact", "tenant_id", "contact_id"),
        {"comment": "客户跟进计划"},
    )


class ConversationTodo(Base):
    """会话待办 —— AI Agent 和人工坐席共用同一张表，标记后续跟进的待处理事项。"""

    __tablename__ = "conversation_todos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, comment="所属租户")
    conversation_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("conversations.id"), nullable=False, comment="关联会话")
    contact_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("contacts.id"), nullable=False, comment="关联客户（冗余）")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="待办事项描述")
    keywords: Mapped[list | None] = mapped_column(JSONB, nullable=True, comment="关键词标签 JSON")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending", comment="待办状态: pending / completed / cancelled")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="截止时间")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="完成时间")
    created_by_type: Mapped[str] = mapped_column(String(20), nullable=False, default="agent", server_default="agent", comment="创建来源: agent / human")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")

    __table_args__ = (
        Index("idx_todos_tenant_conversation", "tenant_id", "conversation_id"),
        Index("idx_todos_tenant_contact_status", "tenant_id", "contact_id", "status"),
        {"comment": "会话待办"},
    )
