"""角色与权限服务。

提供租户级角色的 CRUD 和权限分配功能。平台级权限码（MANAGE_TENANTS 等）
禁止分配给租户角色，确保 SaaS 多租户隔离。
"""

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.employee import Employee
from app.models.role import EmployeeRole, Permission, PermissionCode, Role, RolePermission


PLATFORM_ONLY_PERMISSION_CODES = {
    PermissionCode.MANAGE_TENANTS.value,
    PermissionCode.MANAGE_PLANS.value,
    PermissionCode.VIEW_AUDIT_LOGS.value,
    PermissionCode.MANAGE_BACKUPS.value,
    PermissionCode.MANAGE_SYSTEM_SETTINGS.value,
    PermissionCode.EXPORT_DATA.value,
}


async def _validate_tenant_permission_ids(
    db: AsyncSession,
    permission_ids: list[int],
) -> list[int]:
    """校验权限 ID 列表的有效性并去重。

    验证每个 ID 都存在于 Permission 表中，且不包含平台专属权限码。

    参数：
        db: 异步数据库会话。
        permission_ids: 待校验的权限 ID 列表（可能含重复）。

    返回：
        去重后的有效权限 ID 列表。

    异常：
        HTTPException(400): 存在无效权限 ID 或包含平台专属权限。
    """
    unique_ids = list(dict.fromkeys(permission_ids))
    if not unique_ids:
        return []

    rows = (
        await db.execute(
            select(Permission.id, Permission.code).where(Permission.id.in_(unique_ids))
        )
    ).all()
    if len(rows) != len(unique_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="存在无效权限",
        )
    if any(code in PLATFORM_ONLY_PERMISSION_CODES for _, code in rows):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="平台管理权限不能分配给租户角色",
        )
    return unique_ids


async def list_roles(db: AsyncSession, tenant_id: int) -> list[Role]:
    """查询租户下的所有角色（含权限预加载）。

    使用 selectinload 避免 N+1 查询，一次性加载角色的关联权限。

    参数：
        db: 异步数据库会话。
        tenant_id: 租户 ID。

    返回：
        按创建时间排列的角色列表。
    """
    result = await db.execute(
        select(Role)
        .where(Role.tenant_id == tenant_id)
        .options(selectinload(Role.role_permissions).selectinload(RolePermission.permission))
        .order_by(Role.created_at)
    )
    return list(result.scalars().all())


async def get_role(db: AsyncSession, role_id: int, tenant_id: int) -> Role | None:
    """按 ID 获取租户下单个角色（含权限预加载）。

    参数：
        db: 异步数据库会话。
        role_id: 角色 ID。
        tenant_id: 租户 ID。

    返回：
        角色对象，不存在返回 None。
    """
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
    """在租户下创建角色并分配权限。

    权限 ID 经 _validate_tenant_permission_ids 校验后关联，
    平台专属权限会被拒绝。

    参数：
        db: 异步数据库会话。
        tenant_id: 租户 ID。
        name: 角色名称。
        description: 角色描述（可选）。
        permission_ids: 初始权限 ID 列表（可选）。

    返回：
        新创建的角色对象（含已关联权限）。

    异常：
        HTTPException(400): 权限 ID 无效或含平台专属。
    """
    permission_ids = await _validate_tenant_permission_ids(db, permission_ids or [])
    role = Role(tenant_id=tenant_id, name=name, description=description)
    db.add(role)
    await db.flush()

    for permission_id in permission_ids:
        db.add(RolePermission(role_id=role.id, permission_id=permission_id))

    await db.commit()
    created_role = await get_role(db, role.id, tenant_id)
    if created_role is None:
        raise RuntimeError("created role could not be loaded")
    return created_role


async def update_role(db: AsyncSession, role_id: int, tenant_id: int, **kwargs) -> Role | None:
    """部分更新角色信息（名称、描述等）。

    参数：
        db: 异步数据库会话。
        role_id: 角色 ID。
        tenant_id: 租户 ID。
        **kwargs: 要更新的字段名和值。

    返回：
        更新后的角色，不存在返回 None。
    """
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
    """删除角色（级联删除 RolePermission 关联）。

    参数：
        db: 异步数据库会话。
        role_id: 角色 ID。
        tenant_id: 租户 ID。

    返回：
        成功删除返回 True，不存在返回 False。
    """
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
    """获取角色关联的权限列表。

    参数：
        db: 异步数据库会话。
        role_id: 角色 ID。
        tenant_id: 租户 ID。

    返回：
        权限对象列表，角色不存在返回空列表。
    """
    role = await get_role(db, role_id, tenant_id)
    if not role:
        return []
    return [rp.permission for rp in role.role_permissions]


async def set_role_permissions(db: AsyncSession, role_id: int, tenant_id: int, permission_ids: list[int]) -> Role | None:
    """全量设置角色的权限（先清后增）。

    旧权限关联全部删除后重新插入，不会出现孤儿权限。

    参数：
        db: 异步数据库会话。
        role_id: 角色 ID。
        tenant_id: 租户 ID。
        permission_ids: 新权限 ID 列表。

    返回：
        更新后的角色对象，不存在返回 None。

    异常：
        HTTPException(400): 权限 ID 无效或含平台专属。
    """
    role = await db.execute(
        select(Role).where(Role.id == role_id, Role.tenant_id == tenant_id)
    )
    role = role.scalar_one_or_none()
    if not role:
        return None

    permission_ids = await _validate_tenant_permission_ids(db, permission_ids)

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
    """获取员工拥有的全部权限码（所有角色的权限并集）。

    通过三表 JOIN 收集该员工所有角色的权限码，返回去重后的集合。

    注意：is_superuser 不在此处绕过角色权限。平台管理员仅使用
    require_superuser 访问平台接口，前端菜单显隐依赖此处返回的实际角色权限码。

    参数：
        db: 异步数据库会话。
        employee: Employee ORM 对象。

    返回：
        权限码字符串集合。
    """
    result = await db.execute(
        select(Permission.code)
        .select_from(EmployeeRole)
        .join(RolePermission, RolePermission.role_id == EmployeeRole.role_id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(EmployeeRole.employee_id == employee.id)
    )
    return {row[0] for row in result.all()}
