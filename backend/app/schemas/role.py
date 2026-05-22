"""角色与权限 Schema"""

from datetime import datetime

from pydantic import Field, field_serializer

from app.schemas.base import CamelModel


# ── 权限 ──

class PermissionResponse(CamelModel):
    id: int
    code: str
    name: str
    description: str | None = None

    @field_serializer("id")
    def serialize_id(self, value: int) -> str:
        return str(value)


class PermissionGroupedResponse(CamelModel):
    module: str
    permissions: list[PermissionResponse]


# ── 角色 ──

class RoleCreate(CamelModel):
    name: str
    description: str | None = None
    permission_ids: list[int] = Field(default_factory=list)


class RoleUpdate(CamelModel):
    name: str | None = None
    description: str | None = None


class RoleResponse(CamelModel):
    id: int
    tenant_id: int
    name: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("id", "tenant_id")
    def serialize_bigint_id(self, value: int) -> str:
        return str(value)


class RoleDetailResponse(RoleResponse):
    permissions: list[PermissionResponse] = Field(default_factory=list)


class RolePermissionAssign(CamelModel):
    permission_ids: list[int]
