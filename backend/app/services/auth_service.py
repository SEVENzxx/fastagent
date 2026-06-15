"""认证服务：注册、登录、刷新令牌"""

import re
from datetime import datetime, timezone

from fastapi import HTTPException, status
from pypinyin import lazy_pinyin
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.employee import Employee
from app.models.role import EmployeeRole, Permission, PermissionCode, Role, RolePermission
from app.models.tenant import Tenant
from app.utils.id_generator import generate_id


from app.services.role_service import AGENT_PERMISSION_CODES, PLATFORM_ONLY_PERMISSION_CODES


def _slugify(name: str) -> str:
    """生成 URL slug：英文转小写，中文转拼音，混合处理"""
    if not name or not name.strip():
        return f"tenant-{generate_id()}"

    pinyin_list = lazy_pinyin(name)
    slug = "-".join(pinyin_list)
    slug = re.sub(r"[^a-z0-9-]+", "-", slug.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        return f"tenant-{generate_id()}"

    return slug


async def register_tenant(
    db: AsyncSession,
    *,
    company_name: str,
    email: str,
    password: str,
    display_name: str | None = None,
    slug: str | None = None,
) -> dict:
    """注册新租户，同时创建管理员员工。

    在同一个事务中完成：创建 Tenant → 创建 Employee → 创建角色 → 分配权限。
    兼容内部初始化场景。公开注册入口已移除；通过该函数创建的账号始终是租户管理员，
    不具备平台超级管理员权限。
    """
    resolved_slug = slug or _slugify(company_name)

    # 检查 slug 唯一性
    exists: int | None = await db.scalar(select(Tenant.id).where(Tenant.slug == resolved_slug))
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"企业标识 '{resolved_slug}' 已被占用",
        )

    # 创建租户
    tenant = Tenant(name=company_name, slug=resolved_slug)
    db.add(tenant)
    await db.flush()  # 先获取 tenant.id

    # 创建管理员员工
    employee = Employee(
        tenant_id=tenant.id,
        email=email,
        hashed_password=hash_password(password),
        display_name=display_name,
        is_superuser=False,
    )
    db.add(employee)
    await db.flush()

    permissions = list((await db.execute(select(Permission))).scalars().all())
    admin_role = Role(
        tenant_id=tenant.id,
        name="管理员",
        description="租户管理员，拥有该租户的全部业务权限",
    )
    agent_role = Role(
        tenant_id=tenant.id,
        name="坐席",
        description="默认坐席角色，拥有基础业务权限",
    )
    db.add_all([admin_role, agent_role])
    await db.flush()

    for permission in permissions:
        if permission.code not in PLATFORM_ONLY_PERMISSION_CODES:
            db.add(RolePermission(role_id=admin_role.id, permission_id=permission.id))
        if permission.code in AGENT_PERMISSION_CODES:
            db.add(RolePermission(role_id=agent_role.id, permission_id=permission.id))

    db.add(EmployeeRole(employee_id=employee.id, role_id=admin_role.id))

    await db.commit()
    await db.refresh(tenant)
    await db.refresh(employee)

    # 签发令牌
    subject = str(employee.id)
    access_token = create_access_token(subject)
    refresh_token_str = create_refresh_token(subject)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "token_type": "bearer",
        "user": employee,
        "tenant": tenant,
    }


async def login(db: AsyncSession, *, email: str, password: str) -> dict:
    """员工登录校验，返回令牌 + 用户信息。"""
    result = await db.execute(
        select(Employee)
        .where(Employee.email == email, Employee.deleted_at.is_(None))
    )
    employee = result.scalars().first()

    if not employee or not verify_password(password, employee.hashed_password):
        from app.services.operations_service import record_login
        await record_login(
            db,
            email=email,
            success=False,
            tenant_id=employee.tenant_id if employee else None,
            employee_id=employee.id if employee else None,
            failure_reason="邮箱或密码错误",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )

    # 更新最后登录时间和在线状态
    employee.last_login_at = datetime.now(timezone.utc)
    employee.online_status = "online"
    await db.commit()
    await db.refresh(employee)
    from app.services.operations_service import record_audit, record_login
    await record_login(
        db,
        email=email,
        success=True,
        tenant_id=employee.tenant_id,
        employee_id=employee.id,
    )
    await record_audit(
        db,
        action="login",
        resource_type="employee",
        tenant_id=employee.tenant_id,
        employee_id=employee.id,
        resource_id=employee.id,
    )

    subject = str(employee.id)
    return {
        "access_token": create_access_token(subject),
        "refresh_token": create_refresh_token(subject),
        "token_type": "bearer",
        "user": employee,
    }


async def logout(db: AsyncSession, *, employee_id: int) -> None:
    """设置员工为离线状态。"""
    result = await db.execute(
        select(Employee).where(Employee.id == employee_id, Employee.deleted_at.is_(None))
    )
    employee = result.scalars().first()
    if employee is not None:
        employee.online_status = "offline"
        await db.commit()


async def refresh_token(db: AsyncSession, *, token: str) -> dict:
    """使用 refresh token 换取新的 token 对。"""
    try:
        payload = decode_token(token, expected_type="refresh")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="刷新令牌无效或已过期",
        )

    employee_id = int(payload["sub"])
    employee = await db.get(Employee, employee_id)

    if not employee or employee.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已注销",
        )

    subject = str(employee.id)
    return {
        "access_token": create_access_token(subject),
        "refresh_token": create_refresh_token(subject),
        "token_type": "bearer",
    }
