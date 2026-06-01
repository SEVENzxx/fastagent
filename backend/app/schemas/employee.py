"""员工管理 Schema"""

from datetime import datetime

from pydantic import EmailStr, Field, field_serializer, field_validator

from app.schemas.base import CamelModel
from app.schemas.role import RoleResponse


class EmployeeCreate(CamelModel):
    email: EmailStr
    password: str
    display_name: str | None = None
    avatar_url: str | None = None
    phone: str | None = None
    skills: list[str] | None = None
    max_concurrent_chats: int = 10

    @field_validator("password")
    @classmethod
    def password_min_length(cls, value: str) -> str:
        if len(value) < 6:
            raise ValueError("密码至少需要 6 个字符")
        return value


class EmployeeUpdate(CamelModel):
    display_name: str | None = None
    avatar_url: str | None = None
    phone: str | None = None
    skills: list[str] | None = None
    max_concurrent_chats: int | None = None


class EmployeeResponse(CamelModel):
    id: int
    tenant_id: int
    email: str
    display_name: str | None = None
    avatar_url: str | None = None
    phone: str | None = None
    is_superuser: bool
    online_status: str
    skills: list[str] | None = None
    max_concurrent_chats: int
    last_login_at: datetime | None = None
    created_at: datetime

    @field_serializer("id", "tenant_id")
    def serialize_bigint_id(self, value: int) -> str:
        return str(value)


class EmployeeDetailResponse(EmployeeResponse):
    roles: list[RoleResponse] = Field(default_factory=list)


class EmployeeRoleAssign(CamelModel):
    role_ids: list[int]


class ProfileResponse(CamelModel):
    id: int
    email: str
    display_name: str | None = None
    avatar_url: str | None = None
    phone: str | None = None
    skills: list[str] | None = None

    @field_serializer("id")
    def serialize_id(self, value: int) -> str:
        return str(value)


class ProfileUpdate(CamelModel):
    display_name: str | None = None
    avatar_url: str | None = None
    phone: str | None = None
    skills: list[str] | None = None


class PasswordChange(CamelModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def new_password_min_length(cls, value: str) -> str:
        if len(value) < 6:
            raise ValueError("新密码至少需要 6 个字符")
        return value
