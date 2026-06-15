"""员工管理 API"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.database import get_db
from app.dependencies import get_current_user, require_permission
from app.models.employee import Employee
from app.models.role import PermissionCode, Role
from app.schemas.employee import (
    EmployeeCreate,
    EmployeeDetailResponse,
    EmployeeRoleAssign,
    EmployeeUpdate,
    PasswordChange,
    ProfileResponse,
    ProfileUpdate,
)
from app.schemas.role import RoleResponse
from app.services import employee_service

router = APIRouter(prefix="/employees", tags=["员工"])


def _role_to_response(role: Role) -> RoleResponse:
    return RoleResponse(
        id=role.id,
        tenant_id=role.tenant_id,
        name=role.name,
        description=role.description,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


async def _employee_to_detail(
    db: AsyncSession,
    employee: Employee,
    tenant_id: int,
) -> EmployeeDetailResponse:
    roles = await employee_service.get_employee_roles(db, employee.id, tenant_id) or []
    return EmployeeDetailResponse(
        id=employee.id,
        tenant_id=employee.tenant_id,
        email=employee.email,
        display_name=employee.display_name,
        avatar_url=employee.avatar_url,
        phone=employee.phone,
        is_superuser=employee.is_superuser,
        online_status=employee.online_status,
        skills=employee.skills,
        max_concurrent_chats=employee.max_concurrent_chats,
        last_login_at=employee.last_login_at,
        created_at=employee.created_at,
        roles=[_role_to_response(role) for role in roles],
    )


def _profile_to_response(employee: Employee) -> ProfileResponse:
    return ProfileResponse(
        id=employee.id,
        email=employee.email,
        display_name=employee.display_name,
        avatar_url=employee.avatar_url,
        phone=employee.phone,
        skills=employee.skills,
    )


@router.get("", response_model=list[EmployeeDetailResponse])
async def list_employees(
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.VIEW_EMPLOYEES)),
):
    employees = await employee_service.list_employees(db, current_user.tenant_id)
    return [await _employee_to_detail(db, employee, current_user.tenant_id) for employee in employees]


@router.post("", response_model=EmployeeDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_employee(
    body: EmployeeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_EMPLOYEES)),
):
    employee = await employee_service.create_employee(db, current_user.tenant_id, body)
    return await _employee_to_detail(db, employee, current_user.tenant_id)


@router.get("/me/profile", response_model=ProfileResponse)
async def get_profile(
    current_user: Employee = Depends(get_current_user),
):
    return _profile_to_response(current_user)


@router.put("/me/profile", response_model=ProfileResponse)
async def update_profile(
    body: ProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """
    更新当前登录用户的个人资料

    Args:
        body (ProfileUpdate): 个人资料更新请求数据
        db (AsyncSession): 数据库异步会话
        current_user (Employee): 当前认证用户

    Returns:
        UserResponse: 更新后的用户信息响应
    """
    employee = await employee_service.update_profile(db, current_user, body)
    return _profile_to_response(employee)


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChange,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    await employee_service.change_password(db, current_user, body)


@router.get("/{employee_id}", response_model=EmployeeDetailResponse)
async def get_employee(
    employee_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.VIEW_EMPLOYEES)),
):
    employee = await employee_service.get_employee(db, employee_id, current_user.tenant_id)
    if not employee:
        raise HTTPException(status_code=404, detail="员工不存在")
    return await _employee_to_detail(db, employee, current_user.tenant_id)


@router.put("/{employee_id}", response_model=EmployeeDetailResponse)
async def update_employee(
    employee_id: int,
    body: EmployeeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_EMPLOYEES)),
):
    employee = await employee_service.update_employee(db, employee_id, current_user.tenant_id, body)
    if not employee:
        raise HTTPException(status_code=404, detail="员工不存在")
    return await _employee_to_detail(db, employee, current_user.tenant_id)


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_employee(
    employee_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_EMPLOYEES)),
):
    if employee_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录员工")

    target = await employee_service.get_employee(db, employee_id, current_user.tenant_id)
    if not target:
        raise HTTPException(status_code=404, detail="员工不存在")
    if target.is_superuser:
        raise HTTPException(status_code=400, detail="不能删除超级管理员")

    ok = await employee_service.delete_employee(db, employee_id, current_user.tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="员工不存在")


@router.get("/{employee_id}/roles", response_model=list[RoleResponse])
async def get_employee_roles(
    employee_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.VIEW_EMPLOYEES)),
):
    roles = await employee_service.get_employee_roles(db, employee_id, current_user.tenant_id)
    if roles is None:
        raise HTTPException(status_code=404, detail="员工不存在")
    return [_role_to_response(role) for role in roles]


@router.put("/{employee_id}/roles", response_model=list[RoleResponse])
async def set_employee_roles(
    employee_id: int,
    body: EmployeeRoleAssign,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_EMPLOYEES)),
):
    roles = await employee_service.set_employee_roles(
        db,
        employee_id,
        current_user.tenant_id,
        body.role_ids,
    )
    if roles is None:
        raise HTTPException(status_code=404, detail="员工不存在")
    return [_role_to_response(role) for role in roles]
