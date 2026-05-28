"""客户销售记忆模型 — Phase 9 Agent 长期记忆存储。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils.id_generator import generate_id


class SalesMemory(Base):
    """AI Agent 记录的客户偏好、事实和交互记忆。"""

    __tablename__ = "sales_memories"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=generate_id, comment="主键"
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, comment="租户ID"
    )
    contact_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("contacts.id"), nullable=False, comment="客户ID"
    )
    memory_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="preference",
        server_default="preference", comment="记忆类型: preference/note/fact"
    )
    key: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="记忆键: favorite_flavor/budget_range/常用地址"
    )
    value: Mapped[str] = mapped_column(
        Text, nullable=False, comment="记忆值"
    )
    source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="ai_deduction",
        server_default="ai_deduction", comment="来源: customer_message/agent_note/ai_deduction"
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True, comment="扩展元数据"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    __table_args__ = (
        Index("idx_sm_tenant_contact", "tenant_id", "contact_id"),
        Index("idx_sm_key", "tenant_id", "contact_id", "key", unique=True),
        {"comment": "客户销售记忆表"},
    )
