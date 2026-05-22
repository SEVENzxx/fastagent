"""角色与权限模型"""

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func, text

from app.models.base import Base


# ── 角色 ──────────────────────────────────────────────────────────────────

class Role(Base):
    """租户自定义角色"""

    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
        comment="主键",
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
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

    __table_args__ = (
        Index("idx_roles_tenant_name", "tenant_id", "name", unique=True),
        {"comment": "角色表"},
    )


# ── 权限码枚举 ───────────────────────────────────────────────────────────

class PermissionCode(str, Enum):
    VIEW_ALL_CHATS = "view_all_chats"
    EXPORT_DATA = "export_data"
    MANAGE_KB = "manage_kb"
    MANAGE_TEAM = "manage_team"
    MANAGE_DATABASE = "manage_database"


# ── 权限 ──────────────────────────────────────────────────────────────────

class Permission(Base):
    """系统权限码"""

    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
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

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id"),
        primary_key=True,
        comment="角色 ID",
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("permissions.id"),
        primary_key=True,
        comment="权限 ID",
    )

    __table_args__ = (
        Index("idx_role_permissions_permission", "permission_id"),
        {"comment": "角色-权限关联表"},
    )


# ── 员工-角色关联 ─────────────────────────────────────────────────────────

class EmployeeRole(Base):
    """员工与角色的多对多关联"""

    __tablename__ = "employee_roles"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id"),
        primary_key=True,
        comment="员工 ID",
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id"),
        primary_key=True,
        comment="角色 ID",
    )

    __table_args__ = (
        Index("idx_employee_roles_role", "role_id"),
        {"comment": "员工-角色关联表"},
    )
