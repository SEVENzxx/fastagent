# tests/test_auth_service.py
"""认证服务验收测试 —— 需要连接数据库"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth_service import register_tenant, login
from app.database import AsyncSessionLocal


@pytest.mark.asyncio
async def test_register_tenant():
    """注册租户 + 员工，返回双 Token"""
    async with AsyncSessionLocal() as db:
        result = await register_tenant(
            db=db,
            company_name="测试公司",
            email="test@example.com",
            password="password123",
            display_name="张三",
        )

        assert "access_token" in result
        assert "refresh_token" in result
        assert result["token_type"] == "bearer"

        tenant = result["tenant"]
        assert tenant.name == "测试公司"
        assert tenant.slug is not None  # ← 不固定具体值

        print(f"注册成功: slug={tenant.slug}")


@pytest.mark.asyncio
async def test_login_success():
    """先注册，再登录，拿到 token pair"""
    async with AsyncSessionLocal() as db:
        # 先注册
        await register_tenant(
            db=db,
            company_name="登录测试公司",
            email="login@test.com",
            password="mypassword",
        )

        # 再登录
        result = await login(
            db=db,
            email="login@test.com",
            password="mypassword",
        )

        assert "access_token" in result
        assert "refresh_token" in result
        print(f"登录成功")


@pytest.mark.asyncio
async def test_login_wrong_password():
    """密码错误，登录失败"""
    from fastapi import HTTPException

    async with AsyncSessionLocal() as db:
        # 先注册
        await register_tenant(
            db=db,
            company_name="密码测试",
            email="pwd@test.com",
            password="correct123",
        )

        # 密码错误
        with pytest.raises(HTTPException) as exc_info:
            await login(
                db=db,
                email="pwd@test.com",
                password="wrong456",
            )

        assert exc_info.value.status_code == 401
        print("密码错误测试通过")