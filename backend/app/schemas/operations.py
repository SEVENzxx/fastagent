"""运营支撑 API Schema。"""

from datetime import datetime

from pydantic import Field, field_serializer, field_validator

from app.schemas.base import CamelModel


class SensitiveWordCreate(CamelModel):
    """创建敏感词请求"""

    word: str = Field(description="敏感词内容")
    action: str = Field(default="warn", description="触发动作（block/transfer/warn）")
    is_active: bool = Field(default=True, description="是否启用")

    @field_validator("word")
    @classmethod
    def validate_word(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("敏感词不能为空")
        return value

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: str) -> str:
        if value not in {"block", "transfer", "warn"}:
            raise ValueError("敏感词动作只能为 block、transfer 或 warn")
        return value


class SensitiveWordUpdate(CamelModel):
    """更新敏感词请求"""

    word: str | None = Field(default=None, description="敏感词内容")
    action: str | None = Field(default=None, description="触发动作（block/transfer/warn）")
    is_active: bool | None = Field(default=None, description="是否启用")

    @field_validator("word")
    @classmethod
    def validate_word(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("敏感词不能为空")
        return value

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: str | None) -> str | None:
        if value is not None and value not in {"block", "transfer", "warn"}:
            raise ValueError("敏感词动作只能为 block、transfer 或 warn")
        return value


class SensitiveWordResponse(CamelModel):
    """敏感词响应"""

    id: int = Field(description="敏感词 ID")
    tenant_id: int | None = Field(default=None, description="租户 ID")
    word: str = Field(description="敏感词内容")
    action: str = Field(description="触发动作")
    is_active: bool = Field(description="是否启用")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")

    @field_serializer("id", "tenant_id")
    def serialize_id(self, value: int | None) -> str | None:
        return str(value) if value is not None else None


class NotificationResponse(CamelModel):
    """通知响应"""

    id: int = Field(description="通知 ID")
    type: str = Field(description="通知类型")
    level: str = Field(description="通知级别")
    title: str = Field(description="通知标题")
    content: str | None = Field(default=None, description="通知内容")
    resource_type: str | None = Field(default=None, description="关联资源类型")
    resource_id: int | None = Field(default=None, description="关联资源 ID")
    metadata: dict = Field(description="通知元数据")
    is_read: bool = Field(description="是否已读")
    read_at: datetime | None = Field(default=None, description="读取时间")
    created_at: datetime = Field(description="创建时间")

    @field_serializer("id", "resource_id")
    def serialize_id(self, value: int | None) -> str | None:
        return str(value) if value is not None else None


class AuditLogResponse(CamelModel):
    """审计日志响应"""

    id: int = Field(description="日志 ID")
    tenant_id: int | None = Field(default=None, description="租户 ID")
    employee_id: int | None = Field(default=None, description="操作员工 ID")
    action: str = Field(description="操作动作")
    resource_type: str = Field(description="资源类型")
    resource_id: int | None = Field(default=None, description="资源 ID")
    details: dict = Field(description="操作详情")
    ip_address: str | None = Field(default=None, description="请求 IP 地址")
    user_agent: str | None = Field(default=None, description="请求 User-Agent")
    created_at: datetime = Field(description="创建时间")

    @field_serializer("id", "tenant_id", "employee_id", "resource_id")
    def serialize_id(self, value: int | None) -> str | None:
        return str(value) if value is not None else None


class LoginHistoryResponse(CamelModel):
    """登录历史响应"""

    id: int = Field(description="记录 ID")
    tenant_id: int | None = Field(default=None, description="租户 ID")
    employee_id: int | None = Field(default=None, description="员工 ID")
    email: str = Field(description="登录邮箱")
    success: bool = Field(description="是否成功")
    failure_reason: str | None = Field(default=None, description="失败原因")
    ip_address: str | None = Field(default=None, description="登录 IP")
    user_agent: str | None = Field(default=None, description="登录 User-Agent")
    created_at: datetime = Field(description="创建时间")

    @field_serializer("id", "tenant_id", "employee_id")
    def serialize_id(self, value: int | None) -> str | None:
        return str(value) if value is not None else None
