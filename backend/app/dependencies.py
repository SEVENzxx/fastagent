"""FastAPI 依赖注入"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.database import get_db
from app.models.employee import Employee
from app.services.role_service import get_employee_permission_codes

_bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Employee:
    """从 Authorization header 中解析 JWT，返回当前登录员工。"""
    token = credentials.credentials

    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌无效或已过期",
        )

    employee_id = int(payload["sub"])
    employee = await db.get(Employee, employee_id)

    if not employee or employee.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已注销",
        )

    return employee


def require_permission(code: str):
    """要求租户员工拥有指定权限码。"""

    async def checker(
        current_user: Employee = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> Employee:
        # 超管拥有所有权限，自动放行
        if current_user.is_superuser:
            return current_user

        codes = await get_employee_permission_codes(db, current_user)
        if code not in codes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"缺少权限: {code}",
            )
        return current_user

    return checker


async def require_tenant_user(
    current_user: Employee = Depends(get_current_user),
) -> Employee:
    """要求当前用户是租户员工，而不是平台超级管理员。"""
    if current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="平台管理员不能访问租户业务接口",
        )
    return current_user


async def require_superuser(
    current_user: Employee = Depends(get_current_user),
) -> Employee:
    """要求当前用户为平台超级管理员。"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要超级管理员权限",
        )
    return current_user
