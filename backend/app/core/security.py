"""安全工具：密码哈希 + JWT 签发 / 解码"""

from datetime import datetime, timedelta, timezone

from jose import jwt, JWTError
from passlib.context import CryptContext

from app.config import settings

# ── 密码哈希上下文 ─────────────────────────────────────────────────────────

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """对明文密码进行 bcrypt 哈希。"""
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码与哈希值是否匹配。"""
    return _pwd_context.verify(plain_password, hashed_password)


# ── JWT 令牌 ──────────────────────────────────────────────────────────────

ACCESS_TOKEN_EXPIRE_MINUTES = settings.JWT_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = 7


def _create_token(data: dict, expires_delta: timedelta) -> str:
    """通用 JWT 签发。"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(subject: str) -> str:
    """签发访问令牌（短有效期）。"""
    return _create_token(
        data={"sub": subject, "type": "access"},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(subject: str) -> str:
    """签发刷新令牌（长有效期，7 天）。"""
    return _create_token(
        data={"sub": subject, "type": "refresh"},
        expires_delta=timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str, expected_type: str = "access") -> dict:
    """解码并校验 JWT，返回 payload。无效令牌抛出 JWTError。"""
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])

    if payload.get("type") != expected_type:
        raise JWTError(f"Invalid token type: expected {expected_type}, got {payload.get('type')}")

    return payload