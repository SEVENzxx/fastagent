"""FastAPI 依赖注入"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.database import get_db
from app.models.employee import Employee

_bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> type[Employee]:
    """从 Authorization header 中解析 JWT，返回当前登录员工。

    用法：
        @app.get("/me")
        async def me(current_user = Depends(get_current_user)):
            return current_user
    """
    token = credentials.credentials

    # 解码 JWT
    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌无效或已过期",
        )

    # 查询员工
    employee_id = int(payload["sub"])
    employee = await db.get(Employee, employee_id)

    if not employee or employee.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已注销",
        )

    return employee
