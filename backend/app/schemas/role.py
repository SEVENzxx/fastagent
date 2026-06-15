"""角色与权限 Schema"""

from datetime import datetime

from pydantic import Field, field_serializer

from app.schemas.base import CamelModel


# ── 权限 ──

class PermissionResponse(CamelModel):
    """权限响应"""

    id: int = Field(description="权限 ID")
    code: str = Field(description="权限码")
    name: str = Field(description="权限名称")
    description: str | None = Field(default=None, description="权限描述")

    @field_serializer("id")
    def serialize_id(self, value: int) -> str:
        return str(value)


class PermissionGroupedResponse(CamelModel):
    """按模块分组的权限响应"""

    module: str = Field(description="模块名称")
    permissions: list[PermissionResponse] = Field(description="该模块下的权限列表")


# ── 角色 ──

class RoleCreate(CamelModel):
    """创建角色请求"""

    name: str = Field(description="角色名称")
    description: str | None = Field(default=None, description="角色描述")
    permission_ids: list[int] = Field(default_factory=list, description="权限 ID 列表")


class RoleUpdate(CamelModel):
    """更新角色请求"""

    name: str | None = Field(default=None, description="角色名称")
    description: str | None = Field(default=None, description="角色描述")


class RoleResponse(CamelModel):
    """角色响应"""

    id: int = Field(description="角色 ID")
    tenant_id: int = Field(description="租户 ID")
    name: str = Field(description="角色名称")
    description: str | None = Field(default=None, description="角色描述")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")

    @field_serializer("id", "tenant_id")
    def serialize_bigint_id(self, value: int) -> str:
        return str(value)


class RoleDetailResponse(RoleResponse):
    """角色详情响应（含权限列表）"""

    permissions: list[PermissionResponse] = Field(default_factory=list, description="权限列表")


class RolePermissionAssign(CamelModel):
    """角色授权请求"""

    permission_ids: list[int] = Field(description="权限 ID 列表")
