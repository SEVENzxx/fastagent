"""外部服务客户端基类 — 统一超时/重试/日志/trace_id/headers。

子类通过继承获得统一 HTTP 能力，只需在 __init__ 调用 super().__init__() 并
按需覆盖 _extra_headers() / _request() 即可。
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC
from typing import Any

import httpx

from app.common.trace.context import get_trace_id
from app.integrations.trace_headers import inject_trace_header

logger = logging.getLogger(__name__)


class BaseClientError(RuntimeError):
    """外部服务调用异常基类。"""


class BaseClient(ABC):
    """外部服务客户端基类。

    统一提供以下能力（子类继承后无需重复实现）：
    - 超时管理
    - 重试策略（最多重试 MAX_RETRIES 次，仅 TimeoutException 触发重试）
    - trace_id 透传（X-Trace-Id 请求头自动注入）
    - 中文日志（成功/超时/失败/降级）
    """

    DEFAULT_TIMEOUT_SECONDS: float = 5.0
    MAX_RETRIES: int = 2

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        trust_env: bool = False,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.timeout_seconds = timeout_seconds or self.DEFAULT_TIMEOUT_SECONDS
        self.max_retries = max_retries if max_retries is not None else self.MAX_RETRIES
        self.trust_env = trust_env

    # ── 子类钩子 ──────────────────────────────────────────────────────

    def _extra_headers(self) -> dict[str, str]:
        """子类可重写以注入额外请求头（如 api-key / Content-Type）。

        返回值会与调用方传入的 headers 合并，最终通过 inject_trace_header()
        注入 X-Trace-Id。无需在此方法中重复添加 trace_id。
        """
        return {}

    # ── 底层发送 ──────────────────────────────────────────────────────

    async def _send(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """创建 httpx.AsyncClient 并发送请求，返回原始 Response。

        供需要自定义响应处理的子类使用（如 Qdrant 的非标准状态码检查）。
        普通子类应使用 _request() / _get() / _post()。
        """
        merged = dict(self._extra_headers())
        if headers:
            merged.update(headers)
        merged = inject_trace_header(merged)

        async with httpx.AsyncClient(
            timeout=timeout or self.timeout_seconds,
            trust_env=self.trust_env,
        ) as client:
            return await client.request(
                method, url,
                json=json_body,
                params=params,
                headers=merged,
            )

    # ── 统一请求（含重试） ─────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        timeout: float | None = None,
        retry_on_timeout: bool = True,
    ) -> dict[str, Any]:
        """统一 HTTP 请求入口，含重试/日志/trace_id。

        Args:
            method: HTTP 方法（GET / POST / DELETE 等）
            path: 请求路径（相对于 base_url）
            json_body: 可选的 JSON 请求体
            params: 可选的 URL 查询参数
            timeout: 可选的单次超时，不传时使用实例默认值
            retry_on_timeout: TimeoutException 时是否重试（默认 True）

        Returns:
            响应的 JSON 解析结果

        Raises:
            BaseClientError: 所有可恢复异常转换为此类型
        """
        url = f"{self.base_url}{path}"
        tid = get_trace_id()
        timeout_val = timeout or self.timeout_seconds
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 2):
            try:
                logger.debug(
                    "【外部请求】%s %s trace_id=%s attempt=%s/%s timeout=%ss",
                    method, url, tid, attempt, self.max_retries + 1, timeout_val,
                )
                resp = await self._send(method, url, json_body=json_body, params=params, timeout=timeout_val)
                resp.raise_for_status()
                data = resp.json()

                if attempt > 1:
                    logger.info(
                        "【外部重试成功】%s %s trace_id=%s attempt=%s",
                        method, url, tid, attempt,
                    )
                return data

            except httpx.TimeoutException as exc:
                logger.warning(
                    "【外部超时】%s %s trace_id=%s timeout=%ss attempt=%s/%s",
                    method, url, tid, timeout_val, attempt, self.max_retries + 1,
                )
                last_error = exc
                if retry_on_timeout and attempt <= self.max_retries:
                    await asyncio.sleep(0.5 * attempt)

            except httpx.HTTPError as exc:
                response = getattr(exc, "response", None)
                status = getattr(response, "status_code", "?")
                logger.warning(
                    "【外部失败】%s %s trace_id=%s attempt=%s/%s status=%s",
                    method, url, tid, attempt, self.max_retries + 1,
                    status,
                )
                raise BaseClientError(f"外部服务返回异常: {method} {url}") from exc

            except (TypeError, ValueError) as exc:
                logger.warning(
                    "【外部响应解析失败】%s %s trace_id=%s error=%s",
                    method, url, tid, exc,
                )
                raise BaseClientError("外部服务响应格式异常") from exc

        logger.error(
            "【外部重试耗尽】%s %s trace_id=%s attempts=%s",
            method, url, tid, self.max_retries + 1,
        )
        raise BaseClientError(f"外部服务不可用 (已重试 {self.max_retries} 次): {method} {url}") from last_error

    # ── 便捷方法 ──────────────────────────────────────────────────────

    async def _get(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """GET 请求便捷方法。"""
        return await self._request("GET", path, params=params, timeout=timeout)

    async def _post(
        self,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """POST 请求便捷方法。"""
        return await self._request("POST", path, json_body=json_body, params=params, timeout=timeout)
