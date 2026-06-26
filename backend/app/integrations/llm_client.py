"""统一 LLM 调用客户端。

AI 业务层通过 llm_gateway 声明用途，底层按场景选择模型：
  1. INTENT_JUDGE / GENERAL_REPLY → 平台本地模型（AI_LLM_MODEL）
  2. RAG_REPLY / AGENT            → 租户配置模型，无有效配置时回退平台本地模型
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from app.ai.observability import observe_llm_call, set_observation_io
from app.common.constants.config import TENANT_LLM_CONFIG_CACHE_TTL
from app.common.enums.base import LabeledEnum
from app.common.trace.context import get_trace_id
from app.config import settings
from app.integrations.base import BaseClient, BaseClientError

logger = logging.getLogger(__name__)

LITELLM_DASHSCOPE_PROVIDER = "dashscope"
QWEN_PROVIDER_ALIASES = {"qwen", "dashscope", "aliyun", "alibaba"}
LITELLM_GENERIC_PROVIDERS = {"litellm"}
PROVIDERS_WITH_NATIVE_MODEL_NAMES = {"http", "openai", "ollama", "deepseek", "zhipu"}


def _summarize_messages(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for message in messages[:10]:
        content = str(message.get("content", ""))
        summary.append({
            "role": message.get("role", ""),
            "content": content[:1200],
            "content_len": len(content),
        })
    if len(messages) > 10:
        summary.append({"role": "...", "content": f"{len(messages) - 10} more messages"})
    return summary


class LLMClientError(RuntimeError):
    """模型服务不可用、配置缺失或返回格式异常时抛出。"""


class LLMUseCase(LabeledEnum):
    """模型选择策略。业务层只声明用途，不自行选择模型来源。"""

    INTENT_JUDGE = "intent_judge"
    INTENT_RECALL = "intent_recall"
    GENERAL_REPLY = "general_reply"
    RAG_REPLY = "rag_reply"
    AGENT = "agent"
    PRODUCT_ATTR_EXTRACT = "product_attr_extract"
    PRODUCT_SEMANTIC_SEARCH = "product_semantic_search"
    PRODUCT_EXTRACT = "product_extract"

    @property
    def uses_tenant_config(self) -> bool:
        # TODO: 暂时跳过租户 LLM 配置，全部走本地模型。
        # 恢复时改回: return self in {self.RAG_REPLY, self.AGENT}
        return False

    @property
    def label(self) -> str:
        labels = {
            LLMUseCase.INTENT_JUDGE: "意图判定",
            LLMUseCase.INTENT_RECALL: "意图召回",
            LLMUseCase.GENERAL_REPLY: "通用回复",
            LLMUseCase.RAG_REPLY: "知识库回复",
            LLMUseCase.AGENT: "Agent 推理",
            LLMUseCase.PRODUCT_ATTR_EXTRACT: "商品属性抽取",
            LLMUseCase.PRODUCT_SEMANTIC_SEARCH: "商品语义搜索",
            LLMUseCase.PRODUCT_EXTRACT: "商品参数抽取",
        }
        return labels[self]


class LLMClient(BaseClient):
    """统一 LLM 调用入口 — 仅暴露 complete() 和 stream()。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url if base_url is not None else settings.AI_LLM_BASE_URL,
            timeout_seconds=timeout_seconds or settings.AI_LLM_TIMEOUT_SECONDS,
            trust_env=False,
        )
        self.provider = (provider or settings.AI_LLM_PROVIDER).strip().lower()
        self.api_key = api_key if api_key is not None else settings.AI_LLM_API_KEY
        raw_model = model or settings.AI_LLM_MODEL
        self.model = normalize_litellm_model(raw_model, self.provider)
        logger.info("LLM 客户端已配置：provider=%s model=%s raw_model=%s", self.provider, self.model, raw_model)

    # ═══════════════════════════ 租户配置 ═══════════════════════════

    @classmethod
    async def for_use_case(
        cls,
        use_case: LLMUseCase,
        *,
        tenant_id: int | None = None,
    ) -> LLMClient:
        """按用途选择模型。租户未配置模型时回退到平台本地模型。"""
        if not use_case.uses_tenant_config:
            if use_case == LLMUseCase.GENERAL_REPLY:
                return cls(timeout_seconds=settings.AI_GENERAL_REPLY_TIMEOUT_SECONDS)
            return cls()
        if tenant_id is None:
            logger.warning("租户模型调用缺少 tenant_id：use_case=%s，回退本地模型", use_case.value)
            return cls()
        return await cls._from_tenant(tenant_id) or cls()

    @classmethod
    async def _from_tenant(cls, tenant_id: int) -> LLMClient | None:
        """从租户 LLMConfig 构建客户端，Redis 缓存 24h。"""
        import json as _json
        from app.core.secret_crypto import decrypt_secret

        cache_key = f"fastagent:llm_config:{tenant_id}"

        # 先查 Redis
        try:
            from app.integrations.redis_client import get_redis_client
            redis = get_redis_client()
            raw = await redis.get(cache_key)
            await redis.aclose()
            if raw:
                data = _json.loads(raw)
                if not data.get("is_active", True):
                    return None
                api_key = data.get("api_key")
                if api_key:
                    try:
                        api_key = decrypt_secret(api_key) or ""
                    except Exception:
                        logger.warning("租户 LLM API Key 解密失败（Redis 缓存）：tenant_id=%s", tenant_id)
                        return None
                return cls(
                    provider=data["provider"],
                    api_key=api_key or "",
                    base_url=data.get("api_base") or "",
                    model=data["model"],
                )
        except Exception:
            logger.warning("读取租户 LLM 配置缓存失败：tenant_id=%s，降级查 DB", tenant_id)

        # 回退查 DB
        try:
            from sqlalchemy import select
            from app.integrations.database import AsyncSessionLocal
            from app.models.llm_config import LLMConfig
            from app.models.tenant import Tenant

            async with AsyncSessionLocal() as db:
                config = await db.scalar(
                    select(LLMConfig).join(
                        Tenant, Tenant.selected_llm_config_id == LLMConfig.id
                    ).where(Tenant.id == tenant_id)
                )
                if config is None or not config.is_active:
                    return None

                api_key = config.api_key_encrypted
                if api_key:
                    try:
                        api_key = decrypt_secret(api_key) or ""
                    except Exception:
                        logger.warning("租户 LLM API Key 解密失败：tenant_id=%s", tenant_id)
                        return None

                # 写入 Redis 缓存
                try:
                    redis = get_redis_client()
                    cache_data = _json.dumps({
                        "provider": config.provider,
                        "api_key": config.api_key_encrypted,
                        "api_base": config.api_base,
                        "model": config.model,
                        "is_active": config.is_active,
                    })
                    await redis.setex(cache_key, TENANT_LLM_CONFIG_CACHE_TTL, cache_data)
                    await redis.aclose()
                except Exception:
                    logger.warning("写入租户 LLM 配置缓存失败：tenant_id=%s", tenant_id)

                return cls(
                    provider=config.provider,
                    api_key=api_key or "",
                    base_url=config.api_base or "",
                    model=config.model,
                )
        except Exception as exc:
            logger.warning("加载租户 LLM 配置失败：tenant_id=%s error=%s", tenant_id, exc)
            return None

    # ═══════════════════════════ 公开 API ═══════════════════════════

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """非流式补全（意图精判 / Agent回复 / 技能调用）。"""
        start = time.perf_counter()
        max_tokens = max_tokens or settings.AI_LLM_MAX_TOKENS

        async with observe_llm_call(
            self.model,
            self.provider,
            max_tokens=max_tokens,
            temperature=temperature,
            input_data={"messages": _summarize_messages(messages)},
        ) as observation:
            if self.provider == "http":
                payload = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
                data = await self._http_post("/v1/chat/completions", payload)
                text = self._extract_content(data)
            else:
                response = await self._litellm_call(messages, max_tokens=max_tokens, temperature=temperature, stream=False)
                text = self._extract_content(response)
            set_observation_io(
                observation,
                output_data={"text": text, "text_len": len(text)},
            )

        await self._record_usage(messages, text, self.model, "complete", start)
        return text

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """流式补全（通用回复 SSE 推送）。

        http provider 不支持真流式，退化为 complete + 单次 yield。
        """
        start = time.perf_counter()
        max_tokens = max_tokens or settings.AI_LLM_MAX_TOKENS

        if self.provider == "http":
            text = await self.complete(messages, max_tokens=max_tokens, temperature=temperature)
            yield text
            return

        async with observe_llm_call(
            self.model,
            self.provider,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
            input_data={"messages": _summarize_messages(messages)},
        ) as observation:
            response = await self._litellm_call(messages, max_tokens=max_tokens, temperature=temperature, stream=True)
            collected: list[str] = []
            async for chunk in response:
                delta = self._extract_delta(chunk)
                if delta:
                    collected.append(delta)
                    yield delta
            text = "".join(collected)
            set_observation_io(
                observation,
                output_data={"text": text, "text_len": len(text)},
            )
        await self._record_usage(messages, "".join(collected), self.model, "stream", start)

    # ═══════════════════════════ 内部实现 ═══════════════════════════

    async def _litellm_call(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float | None,
        stream: bool,
    ) -> Any:
        if not self.model:
            raise LLMClientError("模型名称不能为空")

        try:
            from litellm import acompletion
        except ImportError as exc:
            raise LLMClientError("缺少 litellm 依赖") from exc

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "timeout": self.timeout_seconds,
            "stream": stream,
            "max_retries": 0,
            "num_retries": 0,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.base_url:
            kwargs["api_base"] = self.base_url

        try:
            t0 = time.perf_counter()
            return await asyncio.wait_for(acompletion(**kwargs), timeout=self.timeout_seconds + 1)
        except TimeoutError as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.warning(
                "LiteLLM 超时：provider=%s model=%s api_base=%s stream=%s elapsed=%.0fms timeout=%ss",
                self.provider,
                self.model,
                self.base_url,
                stream,
                elapsed,
                self.timeout_seconds,
            )
            raise LLMClientError(f"LiteLLM 超时：model={self.model}") from exc
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.warning(
                "LiteLLM 调用失败：provider=%s model=%s api_base=%s stream=%s elapsed=%.0fms error_type=%s error=%r",
                self.provider,
                self.model,
                self.base_url,
                stream,
                elapsed,
                type(exc).__name__,
                exc,
            )
            raise LLMClientError(f"LiteLLM 错误：{exc}") from exc

    async def _http_post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.base_url:
            raise LLMClientError("AI_LLM_BASE_URL 不能为空")

        url = f"{self.base_url.rstrip('/')}{path}"
        t0 = time.perf_counter()
        logger.debug(
            "HTTP LLM 请求开始：model=%s url=%s timeout=%ss trace_id=%s",
            self.model,
            url,
            self.timeout_seconds,
            get_trace_id(),
        )
        try:
            data = await self._post(path, json_body=payload)
        except BaseClientError as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.warning(
                "HTTP LLM 请求失败：model=%s url=%s elapsed=%.0fms error=%s",
                self.model,
                url,
                elapsed,
                exc,
            )
            raise LLMClientError(f"HTTP LLM 错误：{exc}") from exc

        if not isinstance(data, dict):
            raise LLMClientError("HTTP LLM 响应必须是 JSON 对象")
        return data

    # ── 响应解析 ──

    def _extract_content(self, response: Any) -> str:
        """从 choices[0].message.content 提取文本。"""
        choices = self._get(response, "choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            msg = self._get(first, "message")
            if msg is not None:
                content = self._get(msg, "content")
                if content is not None:
                    return str(content).strip()
            text = self._get(first, "text")
            if text is not None:
                return str(text).strip()
        raise LLMClientError("响应中不包含助手内容")

    def _extract_delta(self, chunk: Any) -> str:
        """从流式 chunk 的 choices[0].delta.content 提取增量文本。"""
        choices = self._get(chunk, "choices")
        if not isinstance(choices, list) or not choices:
            return ""
        delta = self._get(choices[0], "delta")
        if delta is None:
            return ""
        return str(self._get(delta, "content") or "")

    def _get(self, obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    # ── 用量计量 ──

    async def _record_usage(
        self,
        messages: list[dict[str, str]],
        completion_text: str,
        model: str,
        source: str,
        started: float,
    ) -> None:
        """尽力记录用量，失败不阻断回复。"""
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
            logger.warning("记录 LLM 用量失败：model=%s source=%s", model, source)


def normalize_litellm_model(model: str | None, provider: str | None) -> str:
    """Normalize model names for LiteLLM without changing explicit non-Qwen providers."""
    clean_model = str(model or "").strip()
    clean_provider = str(provider or "").strip().lower()
    if not clean_model:
        return clean_model
    if clean_provider in PROVIDERS_WITH_NATIVE_MODEL_NAMES:
        return clean_model
    if clean_model.startswith("dashscope/"):
        return clean_model
    if clean_provider in QWEN_PROVIDER_ALIASES or clean_provider in LITELLM_GENERIC_PROVIDERS:
        if clean_model.startswith("qwen/"):
            suffix = clean_model.split("/", 1)[1].strip()
            return f"{LITELLM_DASHSCOPE_PROVIDER}/{suffix}" if suffix else clean_model
        if "/" not in clean_model and _looks_like_qwen_model(clean_model):
            return f"{LITELLM_DASHSCOPE_PROVIDER}/{clean_model}"
    return clean_model


def _looks_like_qwen_model(model: str) -> bool:
    return model.lower().startswith(("qwen", "qwq", "qvq"))
