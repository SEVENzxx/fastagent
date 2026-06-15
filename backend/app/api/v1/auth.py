"""认证接口：登录、刷新令牌、当前用户。

注册（创建租户 + 管理员）已迁移至平台 Admin API：
  POST /api/v1/admin/tenants — 超管创建租户时自动生成租户管理员账号。
平台不提供公开注册入口，所有租户由超级管理员统一创建和管理。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.database import get_db
from app.dependencies import get_current_user
from app.models.employee import Employee
from app.schemas import (
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth_service import login, logout, refresh_token
from app.services.role_service import get_employee_permission_codes

router = APIRouter(prefix="/auth", tags=["认证"])


# ── 登录 ─────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login_route(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await login(db, email=payload.email, password=payload.password)
    return TokenResponse(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
    )


# ── 登出 ─────────────────────────────────────────────────────────────────

@router.post("/logout", status_code=204)
async def logout_route(
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """设置当前员工为离线状态。"""
    await logout(db, employee_id=current_user.id)
    return None


# ── 刷新令牌 ─────────────────────────────────────────────────────────────

@router.post("/refresh", response_model=TokenResponse)
async def refresh_route(payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    result = await refresh_token(db, token=payload.refresh_token)
    return TokenResponse(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
    )


# ── 当前用户 ─────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserResponse)
async def me(
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = UserResponse.model_validate(current_user)
    result.permissions = list(await get_employee_permission_codes(db, current_user))
    return result
