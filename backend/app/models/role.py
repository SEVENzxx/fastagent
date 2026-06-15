"""角色与权限模型"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.common.enums.base import LabeledEnum
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

class PermissionCode(LabeledEnum):
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
    MANAGE_INTENT_SAMPLES = "manage_intent_samples"

    # ── Admin/超管 ──
    MANAGE_TENANTS = "manage_tenants"
    MANAGE_PLANS = "manage_plans"
    VIEW_AUDIT_LOGS = "view_audit_logs"
    MANAGE_BACKUPS = "manage_backups"
    MANAGE_SYSTEM_SETTINGS = "manage_system_settings"
    EXPORT_DATA = "export_data"

    @property
    def label(self) -> str:
        labels = {
            PermissionCode.VIEW_ASSIGNED_CHATS: "查看分配给我的会话",
            PermissionCode.VIEW_ALL_CHATS: "查看所有会话",
            PermissionCode.MANAGE_CONVERSATIONS: "管理会话（回复/转接/关闭）",
            PermissionCode.VIEW_CONTACTS: "查看客户/联系人列表",
            PermissionCode.MANAGE_CONTACTS: "管理客户/联系人（添加/编辑/删除）",
            PermissionCode.EXPORT_CONTACTS: "导出客户列表",
            PermissionCode.VIEW_PRODUCTS: "查看商品列表",
            PermissionCode.MANAGE_PRODUCTS: "管理商品（添加/编辑/删除）",
            PermissionCode.VIEW_ORDERS: "查看订单列表",
            PermissionCode.MANAGE_ORDERS: "管理订单（创建/编辑）",
            PermissionCode.UPDATE_ORDER_STATUS: "更新订单状态",
            PermissionCode.VIEW_KB: "查看知识库",
            PermissionCode.MANAGE_KB: "管理知识库（上传/编辑/删除）",
            PermissionCode.VIEW_MARKETING: "查看营销资料",
            PermissionCode.MANAGE_MARKETING: "管理营销资料",
            PermissionCode.VIEW_IMAGES: "查看图片库",
            PermissionCode.MANAGE_IMAGES: "管理图片库",
            PermissionCode.VIEW_EMPLOYEES: "查看员工列表",
            PermissionCode.MANAGE_EMPLOYEES: "管理员工（添加/编辑/删除）",
            PermissionCode.MANAGE_ROLES: "管理角色与权限",
            PermissionCode.VIEW_BILLING: "查看计费信息",
            PermissionCode.MANAGE_BILLING: "管理计费设置",
            PermissionCode.VIEW_ANALYTICS: "查看数据分析",
            PermissionCode.EXPORT_ANALYTICS: "导出分析报告",
            PermissionCode.VIEW_CHANNELS: "查看渠道配置",
            PermissionCode.MANAGE_CHANNELS: "管理渠道配置",
            PermissionCode.MANAGE_LLM_CONFIG: "管理 LLM 配置",
            PermissionCode.MANAGE_SENSITIVE_WORDS: "管理敏感词",
            PermissionCode.MANAGE_INTENT_SAMPLES: "管理意图样本",
            PermissionCode.MANAGE_TENANTS: "管理租户（平台专有）",
            PermissionCode.MANAGE_PLANS: "管理套餐（平台专有）",
            PermissionCode.VIEW_AUDIT_LOGS: "查看审计日志（平台专有）",
            PermissionCode.MANAGE_BACKUPS: "管理备份（平台专有）",
            PermissionCode.MANAGE_SYSTEM_SETTINGS: "管理系统设置（平台专有）",
            PermissionCode.EXPORT_DATA: "导出平台数据（平台专有）",
        }
        return labels[self]


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
