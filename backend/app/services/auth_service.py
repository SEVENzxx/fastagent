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


AGENT_PERMISSION_CODES = {
    PermissionCode.VIEW_ASSIGNED_CHATS.value,
    PermissionCode.MANAGE_CONVERSATIONS.value,
    PermissionCode.VIEW_CONTACTS.value,
    PermissionCode.VIEW_PRODUCTS.value,
    PermissionCode.VIEW_ORDERS.value,
    PermissionCode.VIEW_KB.value,
    PermissionCode.VIEW_MARKETING.value,
    PermissionCode.VIEW_IMAGES.value,
}


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

    在同一个事务中完成：创建 Tenant → 创建 Employee（is_superuser=True）
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
        is_superuser=True,
    )
    db.add(employee)
    await db.flush()

    permissions = list((await db.execute(select(Permission))).scalars().all())
    admin_role = Role(
        tenant_id=tenant.id,
        name="管理员",
        description="默认管理员角色，拥有全部权限",
    )
    agent_role = Role(
        tenant_id=tenant.id,
        name="坐席",
        description="默认坐席角色，拥有基础业务权限",
    )
    db.add_all([admin_role, agent_role])
    await db.flush()

    for permission in permissions:
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )

    # 更新最后登录时间
    employee.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(employee)

    subject = str(employee.id)
    return {
        "access_token": create_access_token(subject),
        "refresh_token": create_refresh_token(subject),
        "token_type": "bearer",
        "user": employee,
    }


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
