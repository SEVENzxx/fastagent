"""运营支撑模型 —— 通知、审计日志、登录历史和敏感词管理。

设计意图：
---------
这些表刻意与具体业务表（订单、会话、商品等）解耦。订单模块、会话模块、AI Agent
和 Admin 后台都可以通过统一的 Service 写入运营记录，避免每个模块重复设计日志字段。

重要约定：
---------
- 日志类表（AuditLog、LoginHistory）只追加（INSERT），不物理删除（DELETE），
  便于后续排障追溯和合规审计。
- 租户字段（tenant_id）可为空，表示平台级别的全局记录（如超管操作）。
- JSONB 字段（details、metadata）用于存储半结构化扩展信息，避免频繁修改表结构。

关联关系：
---------
- AuditLog.tenant_id / employee_id → tenants / employees 表
- LoginHistory.tenant_id / employee_id → tenants / employees 表
- SensitiveWord.tenant_id → tenants 表（为空表示平台通用敏感词）
- SystemNotification.tenant_id / employee_id → tenants / employees 表
"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils.id_generator import generate_id


class AuditLog(Base):
    """不可变审计日志 —— 记录人工操作和系统自动化产生的关键副作用。

    业务角色：
    ---------
    这是全平台唯一的审计追踪表。任何关键操作（创建/修改/删除资源、权限变更、
    导出数据、Agent 自动决策等）都必须写入一条审计记录。管理员可在后台按时间、
    操作人、资源类型等维度检索，满足 SOC 2 / ISO 27001 等合规审计要求。

    使用场景：
    ---------
    - 员工手动修改订单状态 → 记录 action="order.status_changed"
    - Agent 自动发送跟进消息 → 记录 action="followup.sent"
    - 管理员导出客户数据 → 记录 action="data.exported"
    - 租户权限变更 → 记录 action="tenant.permission_updated"

    字段说明：
    ---------
    - action: 操作类型，用点号分层命名，如 "order.create" / "user.login"。
    - resource_type: 资源类型标识，如 "order" / "product" / "tenant"。
    - resource_id: 被操作资源的 Snowflake ID，配合 resource_type 可定位具体记录。
    - details: JSONB 存储操作详情（变更前后对比、请求参数等），不做结构化约束。
    - ip_address: 操作来源 IP，IPv6 最长 45 字符。
    - user_agent: 发起请求的 User-Agent 字符串。
    """

    __tablename__ = "audit_logs"

    # ---- 主键 ----
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")

    # ---- 操作者 ----
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=True, comment="所属租户，为空表示平台级操作")

    employee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("employees.id"), nullable=True, comment="操作员工，为空表示系统自动触发")

    # ---- 操作目标 ----
    action: Mapped[str] = mapped_column(String(50), nullable=False, comment="操作类型: order.create / user.login / data.exported")

    resource_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="被操作资源类型: order / product / tenant")

    resource_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="被操作资源ID")

    # ---- 操作详情 ----
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="操作详情 JSON")

    # ---- 来源信息 ----
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True, comment="操作来源IP地址")

    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True, comment="请求 User-Agent")

    # ---- 时间戳 ----
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="操作发生时间")

    # ---- 索引 ----
    __table_args__ = (
        # 租户维度按时间倒序检索（后台审计页面默认排序）
        Index("idx_audit_tenant_time", "tenant_id", created_at.desc()),
        # 按资源类型+ID 快速定位某条记录的所有操作历史
        Index("idx_audit_resource", "resource_type", "resource_id"),
    )


class LoginHistory(Base):
    """登录尝试记录 —— 成功和失败均保留，供安全审计和异常检测使用。

    业务角色：
    ---------
    记录每一次登录尝试（无论成功或失败），是安全审计和异常登录检测的数据基础。
    失败记录可用于识别暴力破解攻击（同一 IP 或邮箱短时间内大量失败尝试），
    成功记录可用于异地登录检测（同一账号短时间内从不同 IP 登录）。

    字段说明：
    ---------
    - email: 尝试登录的邮箱，即使账户不存在也会记录（防止用户名枚举探测）。
    - success: 是否登录成功。
    - failure_reason: 失败原因，如 "invalid_password" / "account_locked" / "tenant_disabled"。
    - ip_address: 登录来源 IP。
    - user_agent: 登录设备的 User-Agent。
    """

    __tablename__ = "login_histories"

    # ---- 主键 ----
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")

    # ---- 身份信息 ----
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=True, comment="所属租户")

    employee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("employees.id"), nullable=True, comment="员工ID")

    email: Mapped[str] = mapped_column(String(255), nullable=False, comment="登录邮箱地址")

    # ---- 登录结果 ----
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"), comment="是否登录成功")

    failure_reason: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="失败原因: invalid_password / account_locked")

    # ---- 来源信息 ----
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True, comment="登录来源IP")

    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True, comment="登录设备 User-Agent")

    # ---- 时间戳 ----
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="登录尝试时间")

    # ---- 索引 ----
    __table_args__ = (
        # 按时间倒序查看最近登录记录
        Index("idx_login_history_time", created_at.desc()),
        # 按邮箱 + 时间检索某用户的所有登录历史（安全审计高频查询）
        Index("idx_login_history_email_time", "email", created_at.desc()),
    )


class SensitiveWord(Base):
    """敏感词 —— 系统级或租户级敏感词过滤规则。

    业务角色：
    ---------
    用于消息发送前的敏感词检查。在 Agent 生成回复或人工坐席发送消息时，
    消息内容会先通过敏感词表做匹配检查。命中规则后根据 action 字段决定
    处理方式：拦截（block）、警告（warn）、或仅记录（log）。

    设计说明：
    ---------
    - tenant_id 为空表示平台通用敏感词规则（所有租户共享生效）。
    - tenant_id 有值表示该租户自定义的敏感词。
    - 检查时平台规则与租户规则同时生效，取最严格的 action 执行。

    字段说明：
    ---------
    - word: 敏感词内容，支持精确匹配或正则表达式。
    - action: 命中后的处理动作 —— "block" 拦截发送 / "warn" 警告但允许 / "log" 仅记录。
    - is_active: 是否启用，停用后不再参与检查。
    """

    __tablename__ = "sensitive_words"

    # ---- 主键 ----
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")

    # ---- 归属 ----
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=True, comment="所属租户，为空表示平台通用")

    # ---- 规则内容 ----
    word: Mapped[str] = mapped_column(String(100), nullable=False, comment="敏感词内容")

    action: Mapped[str] = mapped_column(String(20), nullable=False, default="warn", server_default="warn", comment="处理方式: block / warn / log")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"), comment="是否启用")

    # ---- 时间戳 ----
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # ---- 索引 ----
    __table_args__ = (
        # 按租户 + 启用状态快速加载生效的敏感词列表（消息发送前检查高频查询）
        Index("idx_sensitive_tenant_active", "tenant_id", "is_active"),
        # 唯一约束：同一租户下不允许重复添加相同敏感词
        Index("idx_sensitive_tenant_word", "tenant_id", "word", unique=True),
    )


class SystemNotification(Base):
    """站内通知 —— 发送给租户员工或平台运营人员的系统消息。

    业务角色：
    ---------
    用于在系统内传递非实时通知，如：Agent 完成跟单任务后通知坐席、订单状态
    变更提醒、系统维护公告等。通知在 Agent 工作台前端以消息中心形式展示，
    支持已读/未读状态管理。

    字段说明：
    ---------
    - type: 通知类别，如 "order_alert" / "followup_reminder" / "system_announcement"。
    - level: 通知级别 —— "info" 普通 / "warning" 警告 / "error" 严重。
    - title: 通知标题，前端列表展示。
    - content: 通知正文，支持 Markdown。
    - resource_type / resource_id: 关联的业务资源，点击通知可跳转。
    - metadata_: JSONB 扩展字段，数据库列名 "metadata"（Python 保留字避开）。
    - is_read / read_at: 已读状态追踪。
    """

    __tablename__ = "system_notifications"

    # ---- 主键 ----
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")

    # ---- 接收者 ----
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=True, comment="接收租户，为空发送给平台运营")

    employee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("employees.id"), nullable=True, comment="接收员工，为空广播给租户所有员工")

    # ---- 通知内容 ----
    type: Mapped[str] = mapped_column(String(50), nullable=False, comment="通知类别: order_alert / followup_reminder / system_announcement")

    level: Mapped[str] = mapped_column(String(20), nullable=False, default="info", server_default="info", comment="通知级别: info / warning / error")

    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="通知标题")

    content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="通知正文，支持 Markdown")

    # ---- 关联资源 ----
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="关联资源类型")

    resource_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="关联资源ID")

    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True, comment="扩展信息 JSON")

    # ---- 已读状态 ----
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"), comment="是否已读")

    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="阅读时间")

    # ---- 时间戳 ----
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")

    # ---- 索引 ----
    __table_args__ = (
        # 后台"未读通知"列表的默认查询模式：按租户 + 未读 + 时间倒序
        Index("idx_notification_tenant_read_time", "tenant_id", "is_read", created_at.desc()),
        # 员工维度检索个人未读通知
        Index("idx_notification_employee_read", "employee_id", "is_read"),
    )
