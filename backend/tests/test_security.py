# backend/tests/test_security.py
"""安全工具验收测试"""

from datetime import timedelta

import pytest
from jose import JWTError

from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    _create_token,
)


class TestPassword:
    def test_hash_and_verify(self):
        plain = "my_password_123"
        hashed = hash_password(plain)

        assert verify_password(plain, hashed) is True
        assert verify_password("wrong", hashed) is False

    def test_hash_different_each_time(self):
        plain = "same_password"
        h1 = hash_password(plain)
        h2 = hash_password(plain)
        assert h1 != h2


class TestJWT:
    def test_access_token(self):
        token = create_access_token("user_123")
        payload = decode_token(token)

        assert payload["sub"] == "user_123"
        assert payload["type"] == "access"
        assert "exp" in payload

    def test_refresh_token(self):
        token = create_refresh_token("user_456")
        payload = decode_token(token, expected_type="refresh")

        assert payload["sub"] == "user_456"
        assert payload["type"] == "refresh"

    def test_expired_token(self):
        expired = _create_token(
            {"sub": "user", "type": "access"},
            timedelta(minutes=-1),
        )
        with pytest.raises(JWTError):
            decode_token(expired)

    def test_wrong_type_fails(self):
        refresh = create_refresh_token("user_123")
        with pytest.raises(JWTError):
            decode_token(refresh, expected_type="access")