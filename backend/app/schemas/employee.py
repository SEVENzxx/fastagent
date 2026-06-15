"""员工管理 Schema"""

from datetime import datetime

from pydantic import EmailStr, Field, field_serializer, field_validator

from app.schemas.base import CamelModel
from app.schemas.role import RoleResponse


class EmployeeCreate(CamelModel):
    """创建员工"""

    email: EmailStr = Field(description="邮箱（登录账号）")
    password: str = Field(description="密码")
    display_name: str | None = Field(None, description="显示名称")
    avatar_url: str | None = Field(None, description="头像 URL")
    phone: str | None = Field(None, description="联系电话")
    skills: list[str] | None = Field(None, description="技能标签列表")
    max_concurrent_chats: int = Field(10, description="最大同时接待会话数")

    @field_validator("password")
    @classmethod
    def password_min_length(cls, value: str) -> str:
        if len(value) < 6:
            raise ValueError("密码至少需要 6 个字符")
        return value


class EmployeeUpdate(CamelModel):
    """更新员工信息"""

    display_name: str | None = Field(None, description="显示名称")
    avatar_url: str | None = Field(None, description="头像 URL")
    phone: str | None = Field(None, description="联系电话")
    skills: list[str] | None = Field(None, description="技能标签列表")
    max_concurrent_chats: int | None = Field(None, description="最大同时接待会话数")


class EmployeeResponse(CamelModel):
    """员工响应"""

    id: int = Field(description="员工 ID")
    tenant_id: int = Field(description="租户 ID")
    email: str = Field(description="邮箱")
    display_name: str | None = Field(None, description="显示名称")
    avatar_url: str | None = Field(None, description="头像 URL")
    phone: str | None = Field(None, description="联系电话")
    is_superuser: bool = Field(description="是否超级管理员")
    online_status: str = Field(description="在线状态（online/away/offline）")
    skills: list[str] | None = Field(None, description="技能标签列表")
    max_concurrent_chats: int = Field(description="最大同时接待会话数")
    last_login_at: datetime | None = Field(None, description="最后登录时间")
    created_at: datetime = Field(description="创建时间")

    @field_serializer("id", "tenant_id")
    def serialize_bigint_id(self, value: int) -> str:
        return str(value)


class EmployeeDetailResponse(EmployeeResponse):
    """员工详情（含角色信息）"""

    roles: list[RoleResponse] = Field(default_factory=list, description="角色列表")


class EmployeeRoleAssign(CamelModel):
    """员工角色分配"""

    role_ids: list[int] = Field(description="角色 ID 列表")


class ProfileResponse(CamelModel):
    """当前员工个人信息"""

    id: int = Field(description="员工 ID")
    email: str = Field(description="邮箱")
    display_name: str | None = Field(None, description="显示名称")
    avatar_url: str | None = Field(None, description="头像 URL")
    phone: str | None = Field(None, description="联系电话")
    skills: list[str] | None = Field(None, description="技能标签列表")

    @field_serializer("id")
    def serialize_id(self, value: int) -> str:
        return str(value)


class ProfileUpdate(CamelModel):
    """更新个人信息"""

    display_name: str | None = Field(None, description="显示名称")
    avatar_url: str | None = Field(None, description="头像 URL")
    phone: str | None = Field(None, description="联系电话")
    skills: list[str] | None = Field(None, description="技能标签列表")


class PasswordChange(CamelModel):
    """修改密码"""

    current_password: str = Field(description="当前密码")
    new_password: str = Field(description="新密码")

    @field_validator("new_password")
    @classmethod
    def new_password_min_length(cls, value: str) -> str:
        if len(value) < 6:
            raise ValueError("新密码至少需要 6 个字符")
        return value
