"""认证接口：注册、登录、刷新令牌、当前用户"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.employee import Employee
from app.schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth_service import login, refresh_token, register_tenant

router = APIRouter(prefix="/auth", tags=["认证"])


# ── 注册（创建租户 + 管理员）──────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    result = await register_tenant(
        db,
        company_name=payload.company_name,
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
    )
    return TokenResponse(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
    )


# ── 登录 ─────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login_route(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await login(db, email=payload.email, password=payload.password)
    return TokenResponse(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
    )


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
async def me(current_user: Employee = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)
