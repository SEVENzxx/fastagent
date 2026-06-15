"""渠道配置 Schema。"""

from datetime import datetime

from pydantic import Field, field_serializer, field_validator

from app.schemas.base import CamelModel


PLATFORM_TYPES = {"wecom"}


class PlatformCreate(CamelModel):
    """创建渠道配置请求"""

    type: str = Field(default="wecom", description="渠道类型")
    name: str | None = Field(default="企业微信", description="渠道名称")
    config: dict = Field(default_factory=dict, description="渠道配置信息")
    webhook_url: str | None = Field(default=None, description="Webhook URL")
    is_active: bool = Field(default=True, description="是否启用")

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
    """更新渠道配置请求"""

    name: str | None = Field(default=None, description="渠道名称")
    config: dict | None = Field(default=None, description="渠道配置信息")
    webhook_url: str | None = Field(default=None, description="Webhook URL")
    is_active: bool | None = Field(default=None, description="是否启用")


class PlatformResponse(CamelModel):
    """渠道配置响应"""

    id: int = Field(description="渠道 ID")
    tenant_id: int = Field(description="租户 ID")
    type: str = Field(description="渠道类型")
    name: str | None = Field(default=None, description="渠道名称")
    config: dict = Field(description="渠道配置信息")
    webhook_url: str | None = Field(default=None, description="Webhook URL")
    is_active: bool = Field(description="是否启用")
    created_at: datetime = Field(description="创建时间")

    @field_serializer("id", "tenant_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)


class PlatformListResponse(CamelModel):
    """渠道配置列表响应"""

    items: list[PlatformResponse] = Field(description="渠道配置列表")
    total: int = Field(description="渠道配置总数")
