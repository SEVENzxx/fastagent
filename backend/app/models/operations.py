"""运营支撑模型 —— 通知、审计日志、登录历史、敏感词。"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils.id_generator import generate_id


class AuditLog(Base):
    """不可变审计日志 —— 记录人工操作和系统自动化产生的关键副作用。只追加，不物理删除。"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=True, comment="所属租户，为空表示平台级操作")
    employee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("employees.id"), nullable=True, comment="操作员工，为空表示系统自动触发")
    action: Mapped[str] = mapped_column(String(50), nullable=False, comment="操作类型: order.create / user.login / data.exported")
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="被操作资源类型: order / product / tenant")
    resource_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="被操作资源ID")
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="操作详情 JSON")
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True, comment="操作来源IP地址")
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True, comment="请求 User-Agent")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="操作发生时间")

    __table_args__ = (
        Index("idx_audit_tenant_time", "tenant_id", created_at.desc()),
        Index("idx_audit_resource", "resource_type", "resource_id"),
        {"comment": "审计日志表"},
    )


class LoginHistory(Base):
    """登录尝试记录 —— 成功和失败均保留，供安全审计和异常检测使用。"""

    __tablename__ = "login_histories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=True, comment="所属租户")
    employee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("employees.id"), nullable=True, comment="员工ID")
    email: Mapped[str] = mapped_column(String(255), nullable=False, comment="登录邮箱地址")
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"), comment="是否登录成功")
    failure_reason: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="失败原因: invalid_password / account_locked")
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True, comment="登录来源IP")
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True, comment="登录设备 User-Agent")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="登录尝试时间")

    __table_args__ = (
        Index("idx_login_history_time", created_at.desc()),
        Index("idx_login_history_email_time", "email", created_at.desc()),
        {"comment": "登录历史表"},
    )


class SensitiveWord(Base):
    """敏感词 —— 系统级或租户级敏感词过滤规则。tenant_id 为空表示平台通用规则。"""

    __tablename__ = "sensitive_words"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=True, comment="所属租户，为空表示平台通用")
    word: Mapped[str] = mapped_column(String(100), nullable=False, comment="敏感词内容")
    action: Mapped[str] = mapped_column(String(20), nullable=False, default="warn", server_default="warn", comment="处理方式: block / warn / log")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"), comment="是否启用")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")

    __table_args__ = (
        Index("idx_sensitive_tenant_active", "tenant_id", "is_active"),
        Index("idx_sensitive_tenant_word", "tenant_id", "word", unique=True),
        {"comment": "敏感词表"},
    )


class SystemNotification(Base):
    """站内通知 —— 发送给租户员工或平台运营人员的系统消息，支持已读/未读状态管理。"""

    __tablename__ = "system_notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=True, comment="接收租户，为空发送给平台运营")
    employee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("employees.id"), nullable=True, comment="接收员工，为空广播给租户所有员工")
    type: Mapped[str] = mapped_column(String(50), nullable=False, comment="通知类别: order_alert / followup_reminder / system_announcement")
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="info", server_default="info", comment="通知级别: info / warning / error")
    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="通知标题")
    content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="通知正文，支持 Markdown")
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="关联资源类型")
    resource_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="关联资源ID")
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True, comment="扩展信息 JSON")
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"), comment="是否已读")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="阅读时间")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")

    __table_args__ = (
        Index("idx_notification_tenant_read_time", "tenant_id", "is_read", created_at.desc()),
        Index("idx_notification_employee_read", "employee_id", "is_read"),
        {"comment": "站内通知表"},
    )
