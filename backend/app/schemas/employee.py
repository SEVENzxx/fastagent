"""员工管理 Schema"""

from datetime import datetime

from app.schemas.base import CamelModel
from app.schemas.role import RoleResponse


# ── 员工 ──

class EmployeeCreate(CamelModel):
    email: str
    password: str
    display_name: str | None = None
    avatar_url: str | None = None
    phone: str | None = None
    skills: list[str] | None = None
    max_concurrent_chats: int = 10


class EmployeeUpdate(CamelModel):
    display_name: str | None = None
    avatar_url: str | None = None
    phone: str | None = None
    skills: list[str] | None = None
    max_concurrent_chats: int | None = None
    is_superuser: bool | None = None


class EmployeeResponse(CamelModel):
    id: int
    tenant_id: int
    email: str
    display_name: str | None = None
    avatar_url: str | None = None
    phone: str | None = None
    is_superuser: bool
    online_status: str
    skills: list | None = None
    max_concurrent_chats: int
    last_login_at: datetime | None = None
    created_at: datetime


class EmployeeDetailResponse(EmployeeResponse):
    roles: list[RoleResponse] = []


class EmployeeRoleAssign(CamelModel):
    role_ids: list[int]


class ProfileUpdate(CamelModel):
    display_name: str | None = None
    avatar_url: str | None = None
    phone: str | None = None
    skills: list[str] | None = None


class PasswordChange(CamelModel):
    current_password: str
    new_password: str
