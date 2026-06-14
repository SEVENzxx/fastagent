"""Harness 配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass


# ── 支持的 HTTP 对话后端 ─────────────────────────────────────
BACKEND_NONE = "none"
BACKEND_SIMULATE = "simulate"
SUPPORTED_BACKENDS = [BACKEND_NONE, BACKEND_SIMULATE]

# 默认 Internal Harness API 路径
DEFAULT_HARNESS_ENDPOINT = "/api/v1/internal/harness/messages"


@dataclass
class HarnessConfig:
    """Harness 运行时配置。

    Attributes:
        base_url:             目标服务 base URL（如 ``http://localhost:8000``）。
        tenant_id:            租户 ID。
        backend:              HTTP 对话后端类型（``"none"`` 或 ``"simulate"``）。
        harness_endpoint:     Internal Harness API 路径。
        harness_token_env:    环境变量名，用于读取 Harness API token。
        platform_guid:        WeCom 渠道 ID。
        email:                登录邮箱（用于 JWT 认证）。
        password:             登录密码。
        env_name:             环境名称（local / dev），用于从 YAML env 段选 base_url。
        conversation_prefix:  对话 ID 前缀。
        timeout:              HTTP 请求超时（秒）。
        tag_filter:           只运行指定标签的 case。
        output_path:          JSON 报告保存路径（None=自动生成）。
    """
    base_url: str = "http://localhost:8000"
    tenant_id: int = 0
    backend: str = BACKEND_NONE
    harness_endpoint: str = DEFAULT_HARNESS_ENDPOINT
    harness_token_env: str = "HARNESS_API_TOKEN"
    platform_guid: int = 1
    email: str = ""
    password: str = ""
    env_name: str = "local"
    conversation_prefix: str = "harness"
    timeout: int = 30
    tag_filter: str | None = None
    output_path: str | None = None
    # 内部运行时
    _case_dir: str = ""
    _loaded_from_env: bool = False

    @classmethod
    def from_env(cls) -> HarnessConfig:
        """从环境变量构建配置（CI 友好）。"""
        return cls(
            base_url=os.environ.get("HARNESS_BASE_URL", "http://localhost:8000"),
            tenant_id=int(os.environ.get("HARNESS_TENANT_ID", "0")),
            backend=os.environ.get("HARNESS_BACKEND", BACKEND_NONE),
            harness_endpoint=os.environ.get(
                "HARNESS_ENDPOINT", DEFAULT_HARNESS_ENDPOINT,
            ),
            harness_token_env=os.environ.get(
                "HARNESS_TOKEN_ENV", "HARNESS_API_TOKEN",
            ),
            platform_guid=int(os.environ.get("HARNESS_PLATFORM_GUID", "1")),
            email=os.environ.get("HARNESS_EMAIL", ""),
            password=os.environ.get("HARNESS_PASSWORD", ""),
            env_name=os.environ.get("HARNESS_ENV", "local"),
            timeout=int(os.environ.get("HARNESS_TIMEOUT", "30")),
            tag_filter=os.environ.get("HARNESS_TAG") or None,
            output_path=os.environ.get("HARNESS_OUTPUT") or None,
            _loaded_from_env=True,
        )

    @property
    def harness_token(self) -> str:
        """读取 Harness API token（运行时从环境变量读取）。"""
        return os.environ.get(self.harness_token_env, "")
