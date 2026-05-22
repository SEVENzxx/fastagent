"""认证 Schema 单元测试 —— 纯内存，不连数据库"""

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)


# ══════════════════════════════════════════════════════════════════════════════
# LoginRequest
# ══════════════════════════════════════════════════════════════════════════════

class TestLoginRequest:
    def test_valid_login(self):
        """合法邮箱 + 任意密码 → 通过"""
        data = LoginRequest(email="user@example.com", password="secure123")
        assert data.email == "user@example.com"
        assert data.password == "secure123"

    def test_invalid_email_raises(self):
        """非邮箱格式 → 抛 ValidationError"""
        with pytest.raises(ValidationError):
            LoginRequest(email="not-an-email", password="secret")

    def test_missing_email(self):
        """缺少必填字段 → 抛 ValidationError"""
        with pytest.raises(ValidationError):
            LoginRequest(password="secret")  # type: ignore[call-arg]


# ══════════════════════════════════════════════════════════════════════════════
# RegisterRequest
# ══════════════════════════════════════════════════════════════════════════════

class TestRegisterRequest:
    @pytest.fixture
    def valid_kwargs(self):
        return {
            "email": "new@example.com",
            "password": "strongpass",
            "tenant_id": uuid.uuid4(),
        }

    def test_valid_register(self, valid_kwargs):
        """全部必填项提供 → 通过，display_name 默认 None"""
        data = RegisterRequest(**valid_kwargs)
        assert data.email == "new@example.com"
        assert data.display_name is None
        assert isinstance(data.tenant_id, uuid.UUID)

    def test_optional_display_name(self, valid_kwargs):
        """可选字段 display_name 可传入"""
        data = RegisterRequest(display_name="张三", **valid_kwargs)
        assert data.display_name == "张三"

    def test_password_too_short(self, valid_kwargs):
        """密码 < 6 字符 → 自定义错误"""
        with pytest.raises(ValidationError):
            RegisterRequest(password="12345", **{k: v for k, v in valid_kwargs.items() if k != "password"})

    def test_invalid_email(self, valid_kwargs):
        """邮箱格式错 → 抛 ValidationError"""
        with pytest.raises(ValidationError):
            RegisterRequest(email="bad@@mail..com", **{k: v for k, v in valid_kwargs.items() if k != "email"})

    def test_missing_tenant_id(self, valid_kwargs):
        """缺少 tenant_id → 抛 ValidationError"""
        with pytest.raises(ValidationError):
            RegisterRequest(email="a@b.com", password="secret123")  # type: ignore[call-arg]


# ══════════════════════════════════════════════════════════════════════════════
# TokenResponse
# ══════════════════════════════════════════════════════════════════════════════

class TestTokenResponse:
    def test_default_token_type(self):
        """未传 token_type 时默认为 'bearer'"""
        token = TokenResponse(access_token="jwt-token-string")
        assert token.access_token == "jwt-token-string"
        assert token.token_type == "bearer"
        assert isinstance(token.expires_in, int)

    def test_custom_token_type(self):
        token = TokenResponse(
            access_token="jwt-token-string", token_type="custom", expires_in=7200
        )
        assert token.token_type == "custom"
        assert token.expires_in == 7200


# ══════════════════════════════════════════════════════════════════════════════
# UserResponse — from_attributes 模式
# ══════════════════════════════════════════════════════════════════════════════

class TestUserResponse:
    def test_from_orm_object(self):
        """模拟 ORM 对象 → UserResponse.model_validate(obj) 应成功"""
        now = datetime.now(timezone.utc)

        class FakeEmployee:
            id = uuid.uuid4()
            email = "emp@example.com"
            display_name = "李四"
            is_superuser = False
            tenant_id = uuid.uuid4()
            created_at = now

        user = UserResponse.model_validate(FakeEmployee())
        assert user.email == "emp@example.com"
        assert user.display_name == "李四"
        assert user.is_superuser is False
        assert user.created_at == now

    def test_missing_required_field_raises(self):
        """UserResponse 不用于校验输入，但手动构造时缺字段也报错"""
        with pytest.raises(ValidationError):
            UserResponse(email="a@b.com")  # type: ignore[call-arg]
