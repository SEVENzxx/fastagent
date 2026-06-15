"""联系人模型"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.utils.id_generator import generate_id


class Contact(Base):
    """联系人/客户"""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=generate_id, comment="主键"
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, comment="租户ID"
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="客户名称")
    avatar_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="企业微信头像"
    )
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="电话")
    address: Mapped[str | None] = mapped_column(Text, nullable=True, comment="地址")
    external_ids: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="外部平台ID"
    )
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True, comment="标签")
    merged_from: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("contacts.id"), nullable=True, comment="合并来源联系人ID"
    )
    assigned_employee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id"), nullable=True, comment="分配员工ID"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )

    assigned_employee: Mapped["Employee | None"] = relationship("Employee")

    __table_args__ = (
        Index("idx_contacts_tenant", "tenant_id"),
        Index("idx_contacts_external", "external_ids", postgresql_using="gin"),
        Index("idx_contacts_assigned_employee", "assigned_employee_id"),
        {"comment": "联系人/客户表"},
    )
