"""GENERAL_REPLY 流式回复控制台演示。"""

from __future__ import annotations

import pytest

from app.config import settings
from app.services.ai.intent.pipeline import IntentRecognitionPipeline
from app.services.ai.message_router import MessageRouter


pytestmark = pytest.mark.skipif(
    settings.AI_LLM_PROVIDER == "litellm" and not settings.AI_LLM_API_KEY,
    reason="AI_LLM_PROVIDER=litellm 时需要在 .env 配置 AI_LLM_API_KEY",
)


@pytest.mark.asyncio
async def test_stream_general_reply_to_console(monkeypatch):
    """流式输出 GENERAL_REPLY 回复到控制台。"""
    monkeypatch.setattr(settings, "AI_EMBEDDING_ENABLED", False)

    async def empty_vector_provider(_text: str, _top_k: int, _min_score: float):
        return []

    pipeline = IntentRecognitionPipeline(vector_provider=empty_vector_provider)
    routed = await pipeline.recognize_and_route("我今天好烦啊？")

    print(f"\n[route={routed.route}] ", end="", flush=True)
    async for chunk in MessageRouter().dispatch_stream(routed):
        print(chunk, end="", flush=True)
    print()
