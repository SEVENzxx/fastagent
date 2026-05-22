"""角色 CRUD API"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_permission
from app.models.employee import Employee
from app.models.role import PermissionCode
from app.schemas.role import (
    PermissionResponse,
    RoleCreate,
    RoleDetailResponse,
    RolePermissionAssign,
    RoleUpdate,
)
from app.services import role_service

router = APIRouter(prefix="/roles", tags=["角色"])


def _role_to_response(role) -> RoleDetailResponse:
    perms = []
    if role.role_permissions:
        for rp in role.role_permissions:
            p = rp.permission
            perms.append(PermissionResponse(
                id=p.id, code=p.code, name=p.name, description=p.description,
            ))
    return RoleDetailResponse(
        id=role.id,
        tenant_id=role.tenant_id,
        name=role.name,
        description=role.description,
        created_at=role.created_at,
        updated_at=role.updated_at,
        permissions=perms,
    )


@router.get("", response_model=list[RoleDetailResponse])
async def list_roles(
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """获取租户内所有角色（含权限）"""
    roles = await role_service.list_roles(db, current_user.tenant_id)
    return [_role_to_response(r) for r in roles]


@router.post("", response_model=RoleDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_role(
    body: RoleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_ROLES)),
):
    """创建新角色"""
    role = await role_service.create_role(
        db,
        current_user.tenant_id,
        body.name,
        body.description,
        body.permission_ids,
    )
    return _role_to_response(role)


@router.get("/{role_id}", response_model=RoleDetailResponse)
async def get_role(
    role_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """获取角色详情"""
    role = await role_service.get_role(db, role_id, current_user.tenant_id)
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    return _role_to_response(role)


@router.put("/{role_id}", response_model=RoleDetailResponse)
async def update_role(
    role_id: int,
    body: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_ROLES)),
):
    """更新角色名称/描述"""
    role = await role_service.update_role(
        db, role_id, current_user.tenant_id,
        name=body.name, description=body.description,
    )
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    return _role_to_response(role)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_ROLES)),
):
    """删除角色"""
    ok = await role_service.delete_role(db, role_id, current_user.tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="角色不存在")


@router.get("/{role_id}/permissions", response_model=list[PermissionResponse])
async def get_role_permissions(
    role_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """获取角色已有的权限"""
    perms = await role_service.get_role_permissions(db, role_id, current_user.tenant_id)
    return [
        PermissionResponse(id=p.id, code=p.code, name=p.name, description=p.description)
        for p in perms
    ]


@router.put("/{role_id}/permissions", response_model=RoleDetailResponse)
async def set_role_permissions(
    role_id: int,
    body: RolePermissionAssign,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_ROLES)),
):
    """批量设置角色权限（覆盖式）"""
    role = await role_service.set_role_permissions(
        db, role_id, current_user.tenant_id, body.permission_ids,
    )
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    return _role_to_response(role)
