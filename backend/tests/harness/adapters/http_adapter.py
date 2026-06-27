"""HTTP 黑盒适配器 — 通过 Internal Harness API 执行对话用例。

Phase 1 后端选项：
  - ``"simulate"`` → 调用 ``POST /api/v1/internal/harness/messages``。
  - ``"none"``（默认）→ 抛出引导提示，等待配置后端。

使用方式：
  1. 在目标服务设置 ``HARNESS_API_TOKEN`` 环境变量。
  2. 目标服务需运行在 ``APP_ENV=development`` 或 ``APP_ENV=test``。
  3. Harness 通过 ``X-Harness-Token`` 请求头认证。
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import httpx

from tests.harness.config import (
    BACKEND_NONE,
    BACKEND_SIMULATE,
    HarnessConfig,
)
from tests.harness.schemas import TurnResult


class HttpAdapter:
    """FastAgent HTTP 黑盒适配器。

    职责：
      1. 根据 ``config.backend`` 选择合适的对话后端。
      2. 登录获取 JWT。
      3. 发送消息并记录每轮结果（耗时、状态码、回复、错误）。
      4. 每个 case 使用独立 ``external_user_id`` 以保证对话隔离。
    """

    def __init__(self, config: HarnessConfig) -> None:
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self._token: str | None = None
        self._client = httpx.Client(
            timeout=httpx.Timeout(config.timeout),
            follow_redirects=False,
        )
        self._validate_backend()

    # ── 后端校验 ─────────────────────────────────────────────────────────

    def _validate_backend(self) -> None:
        if self.config.backend not in (BACKEND_NONE, BACKEND_SIMULATE):
            raise ValueError(
                f"不支持的 HTTP 后端: '{self.config.backend}'。"
                f"可选: {BACKEND_NONE}, {BACKEND_SIMULATE}"
            )

    # ── 登录 ────────────────────────────────────────────────────────────────

    @property
    def token(self) -> str:
        if self._token is None:
            raise RuntimeError("尚未登录，请先调用 adapter.login()")
        return self._token

    def login(self, email: str, password: str) -> str:
        """登录并缓存 JWT token。"""
        resp = self._client.post(
            f"{self.base_url}/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"登录失败 (HTTP {resp.status_code}): {resp.text[:200]}"
            )
        data = resp.json()
        self._token = data.get("accessToken") or data.get("access_token", "")
        if not self._token:
            raise RuntimeError("登录响应缺少 accessToken")
        return self._token

    # ── ID 生成 ────────────────────────────────────────────────────────────

    def generate_run_id(self) -> str:
        """为一次 Harness 运行生成唯一 ID。"""
        return f"run_{uuid.uuid4().hex[:16]}"

    def generate_external_user_id(self, case_name: str) -> str:
        """为 case 生成唯一 external_user_id，保证多轮复用同一会话。"""
        suffix = uuid.uuid4().hex[:12]
        prefix = self.config.conversation_prefix
        safe_name = "".join(c for c in case_name if c.isalnum() or c in "-_")[:20]
        return f"{prefix}_{safe_name}_{suffix}"

    # ── 发消息 ──────────────────────────────────────────────────────────────

    def send_message(
        self,
        external_user_id: str,
        content: str,
        *,
        run_id: str | None = None,
    ) -> TurnResult:
        """发送单条客户消息并返回 AI 回复结果。

        Args:
            external_user_id: 外部用户 ID（控制对话复用）。
            content:          消息文本。
            run_id:           Harness 运行 ID（可选，自动生成）。

        Returns:
            单轮对话结果。
        """
        if self.config.backend == BACKEND_SIMULATE:
            return self._send_via_internal(
                external_user_id, content, run_id=run_id,
            )
        elif self.config.backend == BACKEND_NONE:
            return self._mock_turn(content)

        raise NotImplementedError(
            "当前 HTTP 后端未配置。\n\n"
            "Phase 1 Harness 框架已就绪，但 backend 为 'none'。\n"
            "要启用完整功能，请：\n"
            "  1. 在目标服务设置 HARNESS_API_TOKEN 环境变量\n"
            "  2. 确保目标服务运行在 APP_ENV=development\n"
            "  3. 运行 Harness 时指定 --backend simulate\n\n"
            "参见最终说明中的「Phase 3 规划」。"
        )

    # ── mock 后端实现（框架验证） ──────────────────────────────────────────

    def _mock_turn(self, content: str) -> TurnResult:
        """返回 mock 响应（backend=none 框架验证模式用）。"""
        return TurnResult(
            input=content,
            status_code=200,
            reply="[backend=none] skipped actual HTTP call",
            error=None,
        )

    # ── internal 后端实现 ─────────────────────────────────────────────────

    def _send_via_internal(
        self,
        external_user_id: str,
        content: str,
        *,
        run_id: str | None = None,
    ) -> TurnResult:
        """通过 ``POST /api/v1/internal/harness/messages`` 发送消息。"""
        url = f"{self.base_url}{self.config.harness_endpoint}"
        harness_token = self.config.harness_token

        if not harness_token:
            return TurnResult(
                input=content,
                status_code=0,
                error=(
                    f"未设置 Harness API Token。"
                    f"请在环境变量 {self.config.harness_token_env} 中配置。"
                ),
            )

        actual_run_id = run_id or self.generate_run_id()

        start = time.perf_counter()
        result = TurnResult(input=content)

        try:
            headers = {
                "X-Harness-Token": harness_token,
            }
            if self._token is not None:
                headers["Authorization"] = f"Bearer {self._token}"

            resp = self._client.post(
                url,
                headers=headers,
                json={
                    "tenant_id": self.config.tenant_id,
                    "platform_guid": self.config.platform_guid,
                    "run_id": actual_run_id,
                    "external_user_id": external_user_id,
                    "content": content,
                },
            )
        except httpx.TimeoutException:
            result.latency_ms = (time.perf_counter() - start) * 1000
            result.status_code = 0
            result.error = "请求超时"
            return result
        except httpx.RequestError as exc:
            result.latency_ms = (time.perf_counter() - start) * 1000
            result.status_code = 0
            result.error = f"请求异常: {exc}"
            return result

        result.latency_ms = (time.perf_counter() - start) * 1000
        result.status_code = resp.status_code

        if resp.status_code == 200:
            try:
                data = resp.json()
                result.reply = data.get("reply", "")
                result.resource_trace = data.get("resource_trace")
                if not result.reply:
                    result.error = "响应中 reply 为空"
            except Exception as exc:
                result.error = f"解析响应失败: {exc}"
        else:
            result.error = f"HTTP {resp.status_code}: {resp.text[:300]}"

        return result

    # ── 清理 ────────────────────────────────────────────────────────────────

    def cleanup_run(self, run_id: str) -> dict:
        """调用清理接口删除指定 run_id 的测试数据。

        ``DELETE /api/v1/internal/harness/runs/{run_id}``
        """
        url = f"{self.base_url}/api/v1/internal/harness/runs/{run_id}"
        harness_token = self.config.harness_token

        if not harness_token:
            return {"error": "HARNESS_API_TOKEN 未配置"}

        try:
            headers = {
                "X-Harness-Token": harness_token,
            }
            if self._token is not None:
                headers["Authorization"] = f"Bearer {self._token}"

            resp = self._client.delete(
                url,
                headers=headers,
            )
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except httpx.RequestError as exc:
            return {"error": str(exc)}

    # ── 资源释放 ────────────────────────────────────────────────────────────

    def close(self) -> None:
        self._client.close()
