"""员工管理服务"""

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import hash_password, verify_password
from app.models.employee import Employee
from app.models.role import EmployeeRole, Role
from app.schemas.employee import EmployeeCreate, EmployeeUpdate, PasswordChange, ProfileUpdate


def _active_employee_query(tenant_id: int):
    return select(Employee).where(Employee.tenant_id == tenant_id, Employee.deleted_at.is_(None))


async def list_employees(db: AsyncSession, tenant_id: int) -> list[Employee]:
    result = await db.execute(
        _active_employee_query(tenant_id).order_by(Employee.created_at.desc())
    )
    return list(result.scalars().all())


async def get_employee(db: AsyncSession, employee_id: int, tenant_id: int) -> Employee | None:
    result = await db.execute(
        _active_employee_query(tenant_id).where(Employee.id == employee_id)
    )
    return result.scalar_one_or_none()


async def create_employee(db: AsyncSession, tenant_id: int, body: EmployeeCreate) -> Employee:
    existing = await db.scalar(
        select(Employee.id).where(
            Employee.tenant_id == tenant_id,
            Employee.email == body.email,
            Employee.deleted_at.is_(None),
        )
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="邮箱已存在")

    employee = Employee(
        tenant_id=tenant_id,
        email=body.email,
        hashed_password=hash_password(body.password),
        display_name=body.display_name,
        avatar_url=body.avatar_url,
        phone=body.phone,
        skills=body.skills,
        max_concurrent_chats=body.max_concurrent_chats,
        is_superuser=False,
    )
    db.add(employee)
    await db.commit()
    await db.refresh(employee)
    return employee


async def update_employee(
    db: AsyncSession,
    employee_id: int,
    tenant_id: int,
    body: EmployeeUpdate,
) -> Employee | None:
    employee = await get_employee(db, employee_id, tenant_id)
    if not employee:
        return None

    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(employee, key, value)

    await db.commit()
    await db.refresh(employee)
    return employee


async def delete_employee(db: AsyncSession, employee_id: int, tenant_id: int) -> bool:
    employee = await get_employee(db, employee_id, tenant_id)
    if not employee:
        return False

    employee.deleted_at = datetime.now(timezone.utc)
    employee.online_status = "offline"
    await db.execute(delete(EmployeeRole).where(EmployeeRole.employee_id == employee_id))
    await db.commit()
    return True


async def get_employee_roles(db: AsyncSession, employee_id: int, tenant_id: int) -> list[Role] | None:
    employee = await get_employee(db, employee_id, tenant_id)
    if not employee:
        return None

    result = await db.execute(
        select(Role)
        .select_from(EmployeeRole)
        .join(Role, Role.id == EmployeeRole.role_id)
        .where(EmployeeRole.employee_id == employee_id, Role.tenant_id == tenant_id)
        .options(selectinload(Role.role_permissions))
        .order_by(Role.name)
    )
    return list(result.scalars().all())


async def set_employee_roles(
    db: AsyncSession,
    employee_id: int,
    tenant_id: int,
    role_ids: list[int],
) -> list[Role] | None:
    employee = await get_employee(db, employee_id, tenant_id)
    if not employee:
        return None

    unique_role_ids = list(dict.fromkeys(role_ids))
    if unique_role_ids:
        result = await db.execute(
            select(Role.id).where(Role.tenant_id == tenant_id, Role.id.in_(unique_role_ids))
        )
        valid_role_ids = set(result.scalars().all())
        if valid_role_ids != set(unique_role_ids):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="存在无效角色")
    else:
        valid_role_ids = set()

    await db.execute(delete(EmployeeRole).where(EmployeeRole.employee_id == employee_id))
    for role_id in valid_role_ids:
        db.add(EmployeeRole(employee_id=employee_id, role_id=role_id))

    await db.commit()
    roles = await get_employee_roles(db, employee_id, tenant_id)
    return roles or []


async def update_profile(db: AsyncSession, employee: Employee, body: ProfileUpdate) -> Employee:
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(employee, key, value)

    await db.commit()
    await db.refresh(employee)
    return employee


async def change_password(db: AsyncSession, employee: Employee, body: PasswordChange) -> None:
    if not verify_password(body.current_password, employee.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码不正确")

    employee.hashed_password = hash_password(body.new_password)
    await db.commit()
