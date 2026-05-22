"""角色与权限模型"""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base
from app.utils.id_generator import generate_id

if TYPE_CHECKING:
    pass


# ── 角色 ──────────────────────────────────────────────────────────────────

class Role(Base):
    """租户自定义角色"""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_id,
        comment="主键",
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tenants.id"),
        nullable=False,
        comment="所属租户",
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="角色名称"
    )
    description: Mapped[str | None] = mapped_column(Text, comment="角色描述")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )

    # ── 关联 ──
    role_permissions: Mapped[list["RolePermission"]] = relationship(
        "RolePermission", back_populates="role", cascade="all, delete-orphan"
    )
    employee_roles: Mapped[list["EmployeeRole"]] = relationship(
        "EmployeeRole", back_populates="role", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_roles_tenant_name", "tenant_id", "name", unique=True),
        {"comment": "角色表"},
    )


# ── 权限码枚举 ───────────────────────────────────────────────────────────

class PermissionCode(str, Enum):
    # ── 会话 ──
    VIEW_ASSIGNED_CHATS = "view_assigned_chats"
    VIEW_ALL_CHATS = "view_all_chats"
    MANAGE_CONVERSATIONS = "manage_conversations"

    # ── 客户/联系人 ──
    VIEW_CONTACTS = "view_contacts"
    MANAGE_CONTACTS = "manage_contacts"
    EXPORT_CONTACTS = "export_contacts"

    # ── 商品 ──
    VIEW_PRODUCTS = "view_products"
    MANAGE_PRODUCTS = "manage_products"

    # ── 订单 ──
    VIEW_ORDERS = "view_orders"
    MANAGE_ORDERS = "manage_orders"
    UPDATE_ORDER_STATUS = "update_order_status"

    # ── 知识库 ──
    VIEW_KB = "view_kb"
    MANAGE_KB = "manage_kb"

    # ── 营销资料 ──
    VIEW_MARKETING = "view_marketing"
    MANAGE_MARKETING = "manage_marketing"

    # ── 图片库 ──
    VIEW_IMAGES = "view_images"
    MANAGE_IMAGES = "manage_images"

    # ── 员工/团队 ──
    VIEW_EMPLOYEES = "view_employees"
    MANAGE_EMPLOYEES = "manage_employees"
    MANAGE_ROLES = "manage_roles"

    # ── 计费与用量 ──
    VIEW_BILLING = "view_billing"
    MANAGE_BILLING = "manage_billing"

    # ── 数据分析 ──
    VIEW_ANALYTICS = "view_analytics"
    EXPORT_ANALYTICS = "export_analytics"

    # ── 渠道配置 ──
    VIEW_CHANNELS = "view_channels"
    MANAGE_CHANNELS = "manage_channels"

    # ── LLM 与 AI ──
    MANAGE_LLM_CONFIG = "manage_llm_config"
    MANAGE_SENSITIVE_WORDS = "manage_sensitive_words"

    # ── Admin/超管 ──
    MANAGE_TENANTS = "manage_tenants"
    MANAGE_PLANS = "manage_plans"
    VIEW_AUDIT_LOGS = "view_audit_logs"
    MANAGE_BACKUPS = "manage_backups"
    MANAGE_SYSTEM_SETTINGS = "manage_system_settings"
    EXPORT_DATA = "export_data"


# ── 权限 ──────────────────────────────────────────────────────────────────

class Permission(Base):
    """系统权限码"""

    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_id,
        comment="主键",
    )
    code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        comment="权限码: view_all_chats / export_data / manage_kb …",
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="权限名称")
    description: Mapped[str | None] = mapped_column(Text, comment="权限描述")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )


# ── 角色-权限关联 ─────────────────────────────────────────────────────────

class RolePermission(Base):
    """角色与权限的多对多关联"""

    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("roles.id"),
        primary_key=True,
        comment="角色 ID",
    )
    permission_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("permissions.id"),
        primary_key=True,
        comment="权限 ID",
    )

    role: Mapped["Role"] = relationship("Role", back_populates="role_permissions")
    permission: Mapped["Permission"] = relationship("Permission")

    __table_args__ = (
        Index("idx_role_permissions_permission", "permission_id"),
        {"comment": "角色-权限关联表"},
    )


# ── 员工-角色关联 ─────────────────────────────────────────────────────────

class EmployeeRole(Base):
    """员工与角色的多对多关联"""

    __tablename__ = "employee_roles"

    employee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("employees.id"),
        primary_key=True,
        comment="员工 ID",
    )
    role_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("roles.id"),
        primary_key=True,
        comment="角色 ID",
    )

    role: Mapped["Role"] = relationship("Role", back_populates="employee_roles")

    __table_args__ = (
        Index("idx_employee_roles_role", "role_id"),
        {"comment": "员工-角色关联表"},
    )
