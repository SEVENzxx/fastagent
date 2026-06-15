"""认证相关 Schema"""

from datetime import datetime

from pydantic import ConfigDict, EmailStr, field_serializer, field_validator

from app.config import settings
from app.schemas.base import CamelModel


# ── 请求 Schema ───────────────────────────────────────────────────────────

class LoginRequest(CamelModel):
    """登录请求"""

    email: EmailStr
    password: str


class RefreshRequest(CamelModel):
    """刷新令牌请求"""

    refresh_token: str


# ── 响应 Schema ───────────────────────────────────────────────────────────

class TokenResponse(CamelModel):
    """JWT 令牌响应"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = settings.JWT_EXPIRE_MINUTES * 60


class UserResponse(CamelModel):
    """当前用户信息"""

    model_config = ConfigDict(
        alias_generator=CamelModel.model_config["alias_generator"],
        populate_by_name=True,
        from_attributes=True,
    )

    id: int
    email: str
    display_name: str | None = None
    is_superuser: bool
    tenant_id: int
    created_at: datetime
    permissions: list[str] = []

    @field_serializer("id", "tenant_id")
    def serialize_bigint_id(self, value: int) -> str:
        return str(value)
