"""角色与权限服务"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.employee import Employee
from app.models.role import EmployeeRole, Permission, Role, RolePermission


async def list_roles(db: AsyncSession, tenant_id: int) -> list[Role]:
    result = await db.execute(
        select(Role)
        .where(Role.tenant_id == tenant_id)
        .options(selectinload(Role.role_permissions).selectinload(RolePermission.permission))
        .order_by(Role.created_at)
    )
    return list(result.scalars().all())


async def get_role(db: AsyncSession, role_id: int, tenant_id: int) -> Role | None:
    result = await db.execute(
        select(Role)
        .where(Role.id == role_id, Role.tenant_id == tenant_id)
        .options(selectinload(Role.role_permissions).selectinload(RolePermission.permission))
    )
    return result.scalar_one_or_none()


async def create_role(
    db: AsyncSession,
    tenant_id: int,
    name: str,
    description: str | None = None,
    permission_ids: list[int] | None = None,
) -> Role:
    role = Role(tenant_id=tenant_id, name=name, description=description)
    db.add(role)
    await db.flush()

    for permission_id in dict.fromkeys(permission_ids or []):
        db.add(RolePermission(role_id=role.id, permission_id=permission_id))

    await db.commit()
    created_role = await get_role(db, role.id, tenant_id)
    if created_role is None:
        raise RuntimeError("created role could not be loaded")
    return created_role


async def update_role(db: AsyncSession, role_id: int, tenant_id: int, **kwargs) -> Role | None:
    role = await get_role(db, role_id, tenant_id)
    if not role:
        return None
    for key, value in kwargs.items():
        if value is not None:
            setattr(role, key, value)
    await db.commit()
    await db.refresh(role)
    return role


async def delete_role(db: AsyncSession, role_id: int, tenant_id: int) -> bool:
    role = await db.execute(
        select(Role).where(Role.id == role_id, Role.tenant_id == tenant_id)
    )
    role = role.scalar_one_or_none()
    if not role:
        return False
    await db.delete(role)
    await db.commit()
    return True


async def get_role_permissions(db: AsyncSession, role_id: int, tenant_id: int) -> list[Permission]:
    role = await get_role(db, role_id, tenant_id)
    if not role:
        return []
    return [rp.permission for rp in role.role_permissions]


async def set_role_permissions(db: AsyncSession, role_id: int, tenant_id: int, permission_ids: list[int]) -> Role | None:
    role = await db.execute(
        select(Role).where(Role.id == role_id, Role.tenant_id == tenant_id)
    )
    role = role.scalar_one_or_none()
    if not role:
        return None

    # 清除旧关联
    await db.execute(
        delete(RolePermission).where(RolePermission.role_id == role_id)
    )

    # 批量插入新关联
    for perm_id in permission_ids:
        db.add(RolePermission(role_id=role_id, permission_id=perm_id))

    await db.commit()
    return await get_role(db, role_id, tenant_id)


async def get_employee_permission_codes(db: AsyncSession, employee: Employee) -> set[str]:
    """获取员工拥有的全部权限码（所有角色的权限并集）。超管返回全部权限。"""
    if employee.is_superuser:
        result = await db.execute(select(Permission.code))
        return {row[0] for row in result.all()}

    result = await db.execute(
        select(Permission.code)
        .select_from(EmployeeRole)
        .join(RolePermission, RolePermission.role_id == EmployeeRole.role_id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(EmployeeRole.employee_id == employee.id)
    )
    return {row[0] for row in result.all()}
