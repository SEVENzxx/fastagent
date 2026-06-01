"""统一模型调用客户端。"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class LLMClientError(RuntimeError):
    """模型服务不可用、配置缺失或返回格式异常时抛出。"""


class LLMClient:
    """调用平台配置的大模型或小模型。

    `AI_LLM_PROVIDER=http` 时走自部署 8003 服务；`AI_LLM_PROVIDER=litellm`
    时走大厂 API。业务层只使用 `complete()` / `chat()` / `generate()`，
    不直接依赖具体厂商 SDK。
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.provider = (provider or settings.AI_LLM_PROVIDER).strip().lower()
        self.api_key = api_key if api_key is not None else settings.AI_LLM_API_KEY
        self.base_url = base_url if base_url is not None else settings.AI_LLM_BASE_URL
        self.model = model or settings.AI_LLM_MODEL
        self.timeout_seconds = timeout_seconds or settings.AI_LLM_TIMEOUT_SECONDS

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """非流式聊天补全，Intent Judge 默认使用这个入口。"""
        call_started = time.perf_counter()
        selected_model = model or self.model
        if self.provider == "http":
            text = await self._http_openai_complete(
                messages,
                model=selected_model,
                max_tokens=max_tokens or settings.AI_LLM_MAX_TOKENS,
                temperature=temperature,
            )
        else:
            text = await self._acompletion_text(
                messages,
                model=selected_model,
                max_tokens=max_tokens or settings.AI_LLM_MAX_TOKENS,
                temperature=temperature,
                stream=False,
            )
        logger.info(
            "LLM 补全调用完成：provider=%s model=%s messages=%s output_len=%s elapsed_ms=%.0f",
            self.provider,
            selected_model,
            len(messages),
            len(text),
            (time.perf_counter() - call_started) * 1000,
        )
        await self._record_usage(messages, text, selected_model, "complete", call_started)
        return text

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_new_tokens: int | None = None,
        temperature: float | None = None,
        model: str | None = None,
    ) -> str:
        """通用对话补全，GENERAL_REPLY 默认使用这个入口。"""
        call_started = time.perf_counter()
        selected_model = model or self.model
        if self.provider == "http":
            text = await self._http_chat(
                messages,
                max_new_tokens=max_new_tokens or settings.AI_LLM_MAX_TOKENS,
                temperature=temperature,
            )
        else:
            text = await self.complete(
                messages,
                model=selected_model,
                max_tokens=max_new_tokens or settings.AI_LLM_MAX_TOKENS,
                temperature=temperature,
            )
        logger.info(
            "LLM 对话调用完成：provider=%s model=%s messages=%s output_len=%s elapsed_ms=%.0f",
            self.provider,
            selected_model,
            len(messages),
            len(text),
            (time.perf_counter() - call_started) * 1000,
        )
        if self.provider == "http":
            await self._record_usage(messages, text, selected_model, "chat", call_started)
        return text

    async def generate(
        self,
        prompt: str,
        *,
        max_new_tokens: int | None = None,
        temperature: float | None = None,
        model: str | None = None,
    ) -> str:
        """单轮 prompt 补全；内部转成 user message，保持业务接口兼容。"""
        call_started = time.perf_counter()
        selected_model = model or self.model
        if self.provider == "http":
            text = await self._http_generate(
                prompt,
                max_new_tokens=max_new_tokens or settings.AI_LLM_MAX_TOKENS,
                temperature=temperature,
            )
        else:
            text = await self.chat(
                [{"role": "user", "content": prompt}],
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                model=selected_model,
            )
        logger.info(
            "LLM 生成调用完成：provider=%s model=%s prompt_len=%s output_len=%s elapsed_ms=%.0f",
            self.provider,
            selected_model,
            len(prompt),
            len(text),
            (time.perf_counter() - call_started) * 1000,
        )
        if self.provider == "http":
            await self._record_usage([{"role": "user", "content": prompt}], text, selected_model, "generate", call_started)
        return text

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """流式聊天补全；厂商不支持或异常时由上层决定兜底。"""
        call_started = time.perf_counter()
        selected_model = model or self.model
        if self.provider == "http":
            text = await self.complete(
                messages,
                model=selected_model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            logger.info(
                "LLM 流式调用完成（HTTP 非流式兼容）：provider=%s model=%s output_len=%s elapsed_ms=%.0f",
                self.provider,
                selected_model,
                len(text),
                (time.perf_counter() - call_started) * 1000,
            )
            yield text
            return

        response = await self._acompletion(
            messages,
            model=selected_model,
            max_tokens=max_tokens or settings.AI_LLM_MAX_TOKENS,
            temperature=temperature,
            stream=True,
        )
        chunks = 0
        output_len = 0
        collected: list[str] = []
        try:
            async for chunk in response:
                text = self._extract_stream_delta(chunk)
                if text:
                    chunks += 1
                    output_len += len(text)
                    collected.append(text)
                    yield text
            logger.info(
                "LLM 流式调用完成：provider=%s model=%s chunks=%s output_len=%s elapsed_ms=%.0f",
                self.provider,
                selected_model,
                chunks,
                output_len,
                (time.perf_counter() - call_started) * 1000,
            )
            await self._record_usage(messages, "".join(collected), selected_model, "stream", call_started)
        except TypeError as exc:
            raise LLMClientError("litellm stream response is not async iterable") from exc

    async def _acompletion_text(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        max_tokens: int,
        temperature: float | None,
        stream: bool,
    ) -> str:
        response = await self._acompletion(
            messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=stream,
        )
        return self._extract_message_content(response)

    async def _acompletion(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        max_tokens: int,
        temperature: float | None,
        stream: bool,
    ) -> Any:
        if not model:
            raise LLMClientError("AI_LLM_MODEL 不能为空")

        try:
            from litellm import acompletion
        except ImportError as exc:
            raise LLMClientError("缺少 litellm 依赖，请先安装 backend 依赖") from exc

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "timeout": self.timeout_seconds,
            "stream": stream,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.base_url:
            # LiteLLM 使用 api_base 兼容 OpenAI-compatible 服务地址。
            kwargs["api_base"] = self.base_url

        try:
            started = time.perf_counter()
            return await asyncio.wait_for(
                acompletion(**kwargs),
                timeout=self.timeout_seconds + 1,
            )
        except Exception as exc:
            logger.warning(
                "LiteLLM 补全调用失败：provider=%s model=%s stream=%s elapsed_ms=%.0f error=%s",
                self.provider,
                model,
                stream,
                (time.perf_counter() - started) * 1000,
                exc,
            )
            raise LLMClientError(f"litellm completion error: {exc}") from exc

    async def _http_openai_complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        max_tokens: int,
        temperature: float | None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        data = await self._http_post_json("/v1/chat/completions", payload)
        return self._extract_message_content(data)

    async def _http_chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_new_tokens: int,
        temperature: float | None,
    ) -> str:
        payload: dict[str, Any] = {
            "messages": messages,
            "max_new_tokens": max_new_tokens,
            "temperature": temperature,
        }
        data = await self._http_post_json("/chat", payload)
        return self._extract_text(data)

    async def _http_generate(
        self,
        prompt: str,
        *,
        max_new_tokens: int,
        temperature: float | None,
    ) -> str:
        payload: dict[str, Any] = {
            "prompt": prompt,
            "max_new_tokens": max_new_tokens,
            "temperature": temperature,
        }
        data = await self._http_post_json("/generate", payload)
        return self._extract_text(data)

    async def _http_post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.base_url:
            raise LLMClientError("AI_LLM_BASE_URL 不能为空")

        url = f"{self.base_url.rstrip('/')}{path}"
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.warning(
                "HTTP LLM 请求失败：provider=%s path=%s elapsed_ms=%.0f error=%s",
                self.provider,
                path,
                (time.perf_counter() - started) * 1000,
                exc,
            )
            raise LLMClientError(f"http llm error: {exc}") from exc
        except ValueError as exc:
            logger.warning(
                "HTTP LLM 返回非 JSON：provider=%s path=%s elapsed_ms=%.0f",
                self.provider,
                path,
                (time.perf_counter() - started) * 1000,
            )
            raise LLMClientError("http llm response is not valid json") from exc

        if not isinstance(data, dict):
            raise LLMClientError("http llm response must be a json object")
        logger.info(
            "HTTP LLM 请求完成：provider=%s path=%s elapsed_ms=%.0f",
            self.provider,
            path,
            (time.perf_counter() - started) * 1000,
        )
        return data

    def _extract_message_content(self, response: Any) -> str:
        """从 LiteLLM/OpenAI 风格响应中提取 assistant 文本。"""
        choices = self._get_value(response, "choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            message = self._get_value(first, "message")
            if message is not None:
                content = self._get_value(message, "content")
                if content is not None:
                    return str(content).strip()
            text = self._get_value(first, "text")
            if text is not None:
                return str(text).strip()
        raise LLMClientError("litellm response does not contain assistant content")

    def _extract_text(self, data: dict[str, Any]) -> str:
        """兼容自部署模型服务的常见文本返回字段。"""
        for key in ("text", "response", "content", "answer", "generated_text", "result"):
            value = data.get(key)
            if isinstance(value, str):
                return value.strip()
            if isinstance(value, dict):
                nested = self._extract_text(value)
                if nested:
                    return nested

        message = data.get("message")
        if isinstance(message, dict) and message.get("content") is not None:
            return str(message["content"]).strip()

        raise LLMClientError("http llm response does not contain generated text")

    def _extract_stream_delta(self, chunk: Any) -> str:
        choices = self._get_value(chunk, "choices")
        if not isinstance(choices, list) or not choices:
            return ""
        delta = self._get_value(choices[0], "delta")
        if delta is None:
            return ""
        content = self._get_value(delta, "content")
        return str(content or "")

    def _get_value(self, obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    async def _record_usage(
        self,
        messages: list[dict[str, str]],
        completion_text: str,
        model: str,
        source: str,
        started: float,
    ) -> None:
        """尽力写入计量日志，计量失败不能阻断客服回复。"""
        try:
            from app.services.usage_service import record_current_usage
            prompt_text = "\n".join(str(item.get("content") or "") for item in messages)
            await record_current_usage(
                model=model,
                source=source,
                prompt_text=prompt_text,
                completion_text=completion_text,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception:
            logger.exception("LLM 用量日志写入失败，已跳过，不影响当前回复")
