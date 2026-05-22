"""认证相关 Schema"""

from datetime import datetime

from pydantic import ConfigDict, EmailStr, field_validator

from app.config import settings
from app.schemas.base import CamelModel


# ── 请求 Schema ───────────────────────────────────────────────────────────

class LoginRequest(CamelModel):
    """登录请求"""

    email: EmailStr
    password: str


class RegisterRequest(CamelModel):
    """注册请求 — 创建租户 + 管理员"""

    company_name: str
    email: EmailStr
    password: str
    display_name: str | None = None

    @field_validator("company_name")
    @classmethod
    def company_name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("公司名称不能为空")
        return v.strip()

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("密码至少需要 6 个字符")
        return v


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
