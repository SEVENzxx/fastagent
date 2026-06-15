"""AI 业务层统一 LLM 调用入口 — 自动记录 ResourceTrace。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.integrations.llm_client import LLMClient, LLMClientError, LLMUseCase
from app.ai.trace import get_trace, inc_llm
from app.ai.types import Messages

__all__ = ["LLMClientError", "LLMUseCase", "complete", "stream"]


async def complete(
    use_case: LLMUseCase,
    messages: Messages,
    *,
    tenant_id: int | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> str:
    """按业务场景选择模型并执行非流式补全。"""
    trace = get_trace()
    if trace is not None:
        inc_llm(trace)
    client = await LLMClient.for_use_case(use_case, tenant_id=tenant_id)
    return await client.complete(
        messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )


async def stream(
    use_case: LLMUseCase,
    messages: Messages,
    *,
    tenant_id: int | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> AsyncIterator[str]:
    """按业务场景选择模型并执行流式补全。"""
    trace = get_trace()
    if trace is not None:
        inc_llm(trace)
    client = await LLMClient.for_use_case(use_case, tenant_id=tenant_id)
    async for chunk in client.stream(
        messages,
        max_tokens=max_tokens,
        temperature=temperature,
    ):
        yield chunk
