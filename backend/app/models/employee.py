"""员工 / 坐席模型"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func, text

from app.models.base import Base
from app.utils.id_generator import generate_id


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, comment="所属租户")
    email: Mapped[str] = mapped_column(String(255), nullable=False, comment="登录邮箱")
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False, comment="bcrypt 哈希")
    display_name: Mapped[str | None] = mapped_column(String(100), comment="显示名称")
    avatar_url: Mapped[str | None] = mapped_column(String(500), comment="头像")
    phone: Mapped[str | None] = mapped_column(String(50), comment="联系电话")
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), comment="是否超级管理员")
    max_concurrent_chats: Mapped[int] = mapped_column(Integer, default=10, server_default=text("10"), comment="最大同时会话数")
    online_status: Mapped[str] = mapped_column(String(20), default="offline", server_default=text("'offline'"), comment="online / away / busy / offline")
    skills: Mapped[list | None] = mapped_column(JSON, comment='JSONB: ["售前","售后","技术支持"]')
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="软删除")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最后登录时间")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")

    __table_args__ = (
        Index("idx_employees_email_tenant", "email", "tenant_id", unique=True),
        Index("idx_employees_tenant", "tenant_id"),
        {"comment": "员工 / 坐席表"},
    )
