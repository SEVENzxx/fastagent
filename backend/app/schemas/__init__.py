"""Pydantic Schema 包"""

from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    RefreshRequest,
    TokenResponse,
    UserResponse,
)
from app.schemas.role import (
    PermissionGroupedResponse,
    PermissionResponse,
    RoleCreate,
    RoleDetailResponse,
    RolePermissionAssign,
    RoleResponse,
    RoleUpdate,
)

__all__ = [
    "LoginRequest",
    "RegisterRequest",
    "RefreshRequest",
    "TokenResponse",
    "UserResponse",
    "PermissionGroupedResponse",
    "PermissionResponse",
    "RoleCreate",
    "RoleDetailResponse",
    "RolePermissionAssign",
    "RoleResponse",
    "RoleUpdate",
]
