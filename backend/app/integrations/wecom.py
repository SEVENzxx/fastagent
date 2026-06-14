"""企业微信入站消息工具。"""

import base64
import logging
import struct
from dataclasses import dataclass
from hashlib import sha1

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

logger = logging.getLogger(__name__)


@dataclass
class WeComInboundMessage:
    external_userid: str
    name: str | None
    avatar_url: str | None
    content: str
    content_type: str = "text"
    msg_id: str | None = None


def _aes_decrypt(encrypted: bytes, encoding_aes_key: str) -> bytes:
    """企业微信 AES-256-CBC 解密。

    encoding_aes_key: 企微后台 43 位 EncodingAESKey，base64 解码后为 32 字节密钥。
    """
    aes_key = base64.b64decode(encoding_aes_key + "=")
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(aes_key[:16]))
    decryptor = cipher.decryptor()
    padded = decryptor.update(encrypted) + decryptor.finalize()
    pad_len = padded[-1]
    return padded[:-pad_len]


def compute_signature(
    token: str,
    timestamp: str,
    nonce: str,
    content: str = "",
) -> str:
    """计算企业微信回调签名，返回 hex 字符串用于调试对比。"""
    raw = "".join(sorted([token or "", timestamp or "", nonce or "", content or ""]))
    return sha1(raw.encode("utf-8")).hexdigest()


def verify_signature(
    token: str,
    timestamp: str,
    nonce: str,
    signature: str,
    content: str = "",
) -> bool:
    """校验企业微信回调签名。

    URL 验证时 content 传 echostr；消息回调时 content 传加密消息体。
    签名算法：sha1(sort(token, timestamp, nonce, content))。
    """
    if not signature:
        return True
    return compute_signature(token, timestamp, nonce, content) == signature


def decode_echo(echostr: str, encoding_aes_key: str | None = None) -> str:
    """回调 URL 验证：解密 echostr 并返回明文。

    明文模式直接返回原值；安全模式需要 AES 解密。
    解密后的结构：16 随机字节 + 4 字节 msg_len(big-endian) + 明文 + receiveid。
    """
    if not encoding_aes_key:
        return echostr
    encrypted = base64.b64decode(echostr)
    decrypted = _aes_decrypt(encrypted, encoding_aes_key)
    msg_len = struct.unpack(">I", decrypted[16:20])[0]
    return decrypted[20:20 + msg_len].decode("utf-8")


def extract_encrypt_for_signature(body_str: str) -> str:
    """从 XML body 中提取 <Encrypt> 值用于签名验证。

    企业微信 POST 回调的 msg_signature 是用 Encrypt 标签内容（不含标签本身）
    计算的，不是整个 XML body。如果 XML 解析失败或没有 Encrypt 标签，
    回退到原始 body。
    """
    import xml.etree.ElementTree as ET

    if not body_str:
        return ""
    try:
        root = ET.fromstring(body_str)
        encrypt_el = root.find("Encrypt")
        if encrypt_el is not None and encrypt_el.text:
            return encrypt_el.text.strip()
    except ET.ParseError:
        logger.warning("企业微信消息 XML 解析失败：body_prefix=%s", body_str[:200])
    return body_str


def parse_encrypted_xml(body: bytes, config: dict[str, str]) -> WeComInboundMessage:
    """解析企业微信 XML/AES 加密回调消息。

    外层 XML 结构:
      <xml><Encrypt>base64_cipher</Encrypt><AgentID>...</AgentID></xml>

    解密后明文结构: 16 随机字节 + 4 字节 msg_len(big-endian) + XML 明文 + receiveid
    """
    import xml.etree.ElementTree as ET

    encoding_aes_key = config.get("encoding_aes_key", "")
    if not encoding_aes_key:
        raise ValueError("未配置 EncodingAESKey")

    # 1. 外层 XML → Encrypt
    root = ET.fromstring(body.decode("utf-8"))
    encrypt_el = root.find("Encrypt")
    if encrypt_el is None or not encrypt_el.text:
        raise ValueError("回调 XML 缺少 Encrypt 字段")

    # 2. AES-CBC 解密
    encrypted = base64.b64decode(encrypt_el.text)
    decrypted = _aes_decrypt(encrypted, encoding_aes_key)

    # 3. 拆解: random(16) + msg_len(4) + xml + receiveid
    msg_len = struct.unpack(">I", decrypted[16:20])[0]
    xml_plain = decrypted[20:20 + msg_len].decode("utf-8")
    # receiveid = decrypted[20 + msg_len:].decode("utf-8")  # 可用于校验 corpid

    # 4. 明文 XML → 消息字段
    msg = ET.fromstring(xml_plain)

    def _text(tag: str) -> str:
        el = msg.find(tag)
        return (el.text or "").strip() if el is not None else ""

    return WeComInboundMessage(
        external_userid=_text("FromUserName"),
        name=None,
        avatar_url=None,
        content=_text("Content"),
        content_type=_text("MsgType") or "text",
        msg_id=_text("MsgId") or None,
    )
