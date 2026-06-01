"""运营支撑 API Schema。"""

from datetime import datetime

from pydantic import field_serializer, field_validator

from app.schemas.base import CamelModel


class SensitiveWordCreate(CamelModel):
    word: str
    action: str = "warn"
    is_active: bool = True

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
    word: str | None = None
    action: str | None = None
    is_active: bool | None = None

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
    id: int
    tenant_id: int | None = None
    word: str
    action: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @field_serializer("id", "tenant_id")
    def serialize_id(self, value: int | None) -> str | None:
        return str(value) if value is not None else None


class NotificationResponse(CamelModel):
    id: int
    type: str
    level: str
    title: str
    content: str | None = None
    resource_type: str | None = None
    resource_id: int | None = None
    metadata: dict
    is_read: bool
    read_at: datetime | None = None
    created_at: datetime

    @field_serializer("id", "resource_id")
    def serialize_id(self, value: int | None) -> str | None:
        return str(value) if value is not None else None


class AuditLogResponse(CamelModel):
    id: int
    tenant_id: int | None = None
    employee_id: int | None = None
    action: str
    resource_type: str
    resource_id: int | None = None
    details: dict
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime

    @field_serializer("id", "tenant_id", "employee_id", "resource_id")
    def serialize_id(self, value: int | None) -> str | None:
        return str(value) if value is not None else None


class LoginHistoryResponse(CamelModel):
    id: int
    tenant_id: int | None = None
    employee_id: int | None = None
    email: str
    success: bool
    failure_reason: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime

    @field_serializer("id", "tenant_id", "employee_id")
    def serialize_id(self, value: int | None) -> str | None:
        return str(value) if value is not None else None
