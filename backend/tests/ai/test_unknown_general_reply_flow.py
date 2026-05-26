"""未知意图到 GENERAL_REPLY 小模型回复的端到端测试。"""

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
async def test_unknown_intent_routes_to_general_reply_and_calls_small_model(monkeypatch):
    """用户问题无法命中业务意图时，应走 unknown_intent -> GENERAL_REPLY -> 小模型回复。"""
    monkeypatch.setattr(settings, "AI_EMBEDDING_ENABLED", False)

    async def empty_vector_provider(_text: str, _top_k: int, _min_score: float):
        return []

    pipeline = IntentRecognitionPipeline(vector_provider=empty_vector_provider)
    routed = await pipeline.recognize_and_route("我今天好烦啊？")

    print(f"\n routed: {routed}")

    assert routed.primary_intent == "unknown_intent"
    assert routed.route == "GENERAL_REPLY"
    assert routed.skill == "general_reply"

    result = await MessageRouter().dispatch(routed)

    print(f"\n result: {result}")

    assert result.route == "GENERAL_REPLY"
    assert result.skill == "general_reply"
    assert result.message
    assert len(result.message) <= 300
