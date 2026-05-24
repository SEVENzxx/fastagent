"""渠道配置 Schema。"""

from datetime import datetime

from pydantic import Field, field_serializer, field_validator

from app.schemas.base import CamelModel


PLATFORM_TYPES = {"wecom"}


class PlatformCreate(CamelModel):
    type: str = "wecom"
    name: str | None = "企业微信"
    config: dict = Field(default_factory=dict)
    webhook_url: str | None = None
    is_active: bool = True

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in PLATFORM_TYPES:
            raise ValueError("渠道类型不支持")
        return value

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        clean = value.strip()
        return clean or None


class PlatformUpdate(CamelModel):
    name: str | None = None
    config: dict | None = None
    webhook_url: str | None = None
    is_active: bool | None = None


class PlatformResponse(CamelModel):
    id: int
    tenant_id: int
    type: str
    name: str | None = None
    config: dict
    webhook_url: str | None = None
    is_active: bool
    created_at: datetime

    @field_serializer("id", "tenant_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)


class PlatformListResponse(CamelModel):
    items: list[PlatformResponse]
    total: int
