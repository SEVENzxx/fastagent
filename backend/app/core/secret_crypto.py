"""敏感配置加解密工具 —— 对数据库存储的敏感字段（API Key、密钥等）进行对称加解密。

设计意图：
---------
平台需要存储 LLM 供应商的 API Key、企业微信应用的 Secret 等敏感凭证到数据库。
这些值不能明文存储（防止数据库泄漏导致密钥外泄），但又需要在运行时解密使用。
本模块提供统一的 encrypt_secret / decrypt_secret 接口，业务代码无需关心底层
加密算法。

当前实现：
---------
第一版使用应用 SECRET_KEY（来自 .env 配置）通过 SHA-256 派生 32 字节密钥，
再经 Base64 URL-safe 编码生成 Fernet 对称密钥。这保证了：
- 相同的 SECRET_KEY → 相同的 Fernet 密钥 → 加密值可跨进程、跨重启解密。
- 数据库只存密文，运维人员无法直接读取。
- 性能开销极低（Fernet = AES-128-CBC + HMAC-SHA256），不影响 API 响应时间。

升级路径：
---------
后续接入云 KMS（如 AWS KMS / 阿里云 KMS / Azure Key Vault）时，只需要：
1. 替换 _fernet() 函数的内部实现（从 KMS 获取密钥）
2. 迁移已加密的旧值（用旧密钥解密 → 用新密钥重新加密）
3. 业务代码加密/解密调用（encrypt_secret / decrypt_secret）无需任何改动

这是"策略模式"在模块级别的实践——对外接口不变，内部实现可替换。

安全性说明：
-----------
- decrypt_secret 在密钥轮换或历史脏数据导致解密失败时，返回 None 而非抛出异常，
  避免因单条数据问题导致整个请求 500 错误。
- API 响应中绝对不应包含 api_key_encrypted 字段（由 Schema 排除），即使解密后
  的值也不应出现在日志中（由 Service 层控制）。

使用示例：
---------
    from app.core.secret_crypto import encrypt_secret, decrypt_secret

    # 存储前加密
    encrypted = encrypt_secret("sk-abc123")
    config.api_key_encrypted = encrypted

    # 使用前解密
    plain_key = decrypt_secret(config.api_key_encrypted)
    if plain_key is None:
        raise ValueError("密钥解密失败，请检查 SECRET_KEY 是否一致")
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _fernet() -> Fernet:
    """从应用 SECRET_KEY 派生 Fernet 对称加密实例。

    派生过程：
    1. SECRET_KEY → SHA-256 哈希 → 32 字节摘要
    2. 32 字节摘要 → Base64 URL-safe 编码 → 44 字符 Fernet 密钥
    3. 使用该密钥构造 Fernet 实例（AES-128-CBC + HMAC-SHA256）

    Fernet 密钥格式要求：
    - 必须是 32 字节原始密钥经 Base64 URL-safe 编码后的字符串
    - SHA-256 输出恰好 32 字节，满足 Fernet 的密钥长度要求

    返回值：
        Fernet: 用 SECRET_KEY 派生的 Fernet 加密实例
    """
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str | None) -> str | None:
    """加密非空敏感值。

    使用 Fernet 对称加密将明文转换为密文字符串。密文是 Base64 编码的 ASCII 字符串，
    可直接存入数据库 TEXT/VARCHAR 字段。

    参数：
        value: 待加密的明文字符串，为空或 None 时返回 None。

    返回值：
        加密后的 ASCII 密文字符串，或 None（输入为空时）。

    异常：
        无显式异常处理——如果加密失败（密钥损坏等），让异常向上传播，
        因为这通常意味着系统配置错误，不应静默吞掉。

    使用注意：
        密文包含时间戳（Fernet 特性），同一明文每次加密产生的密文不同。
        不要对密文做相等性比较来判断明文是否相同，应先解密再比较。
    """
    if not value:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str | None) -> str | None:
    """解密敏感值；密钥轮换或历史脏数据导致解密失败时返回 None。

    参数：
        value: 待解密的密文字符串，为空或 None 时返回 None。

    返回值：
        解密后的明文字符串，或 None（以下情况）：
        - 输入为空字符串或 None
        - 密文已损坏（数据库手动修改或传输错误）
        - SECRET_KEY 已轮换（旧密文无法用新密钥解密）→ 捕获 InvalidToken
        - 密文 Base64 解码失败 → 捕获 ValueError

    安全性说明：
        返回 None 而非抛出异常，避免因单条配置记录解密失败导致整个 API 请求
        返回 500 错误。调用方应检查返回值是否为 None 并做相应处理（如跳过该
        配置、记录告警日志、通知管理员等）。
    """
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        # InvalidToken: 密钥不匹配或密文被篡改（Fernet HMAC 校验失败）
        # ValueError: 密文 Base64 解码失败（不是合法的 Fernet token 格式）
        return None
