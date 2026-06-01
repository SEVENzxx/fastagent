"""安全工具：密码哈希 + JWT 签发 / 解码"""

from datetime import datetime, timedelta, timezone

import bcrypt
from jose import jwt, JWTError

from app.config import settings

# ── 密码哈希上下文 ─────────────────────────────────────────────────────────
#
# passlib 1.7.4 会在初始化 bcrypt 后端时执行一组旧版兼容探测。bcrypt 5.0 已经
# 对超过 72 字节的输入抛出异常，导致 passlib 的内部探测失败，最终连普通密码也
# 无法哈希。这里直接使用 bcrypt 官方接口，生成的仍然是标准 bcrypt 哈希，因此
# 已有密码无需迁移。


def hash_password(password: str) -> str:
    """对明文密码进行 bcrypt 哈希。

    bcrypt 算法只处理前 72 个字节。静默截断会让两个不同长密码得到相同结果，
    因此明确拒绝超长输入，让调用方返回可解释的校验错误。
    """
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        raise ValueError("密码长度不能超过 72 个字节")
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码与哈希值是否匹配。"""
    password_bytes = plain_password.encode("utf-8")
    if len(password_bytes) > 72:
        return False
    try:
        return bcrypt.checkpw(password_bytes, hashed_password.encode("utf-8"))
    except (TypeError, ValueError):
        # 数据库中若存在损坏哈希，不应让登录接口抛出 500。
        return False


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
