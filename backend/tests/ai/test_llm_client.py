"""统一模型客户端真实 API 测试。"""

from __future__ import annotations

import json

import pytest

from app.config import settings
from app.integrations.llm_client import LLMClient


pytestmark = pytest.mark.skipif(
    settings.AI_LLM_PROVIDER == "litellm" and not settings.AI_LLM_API_KEY,
    reason="AI_LLM_PROVIDER=litellm 时需要在 .env 配置 AI_LLM_API_KEY",
)


@pytest.mark.asyncio
async def test_complete_calls_configured_api_for_intent_judge():
    """候选精判应真实调用当前配置的模型 API，便于约束 JSON 输出。"""
    client = LLMClient()
    result = await client.complete(
        [
            {"role": "system", "content": "你是一个意图分类助手，只返回 JSON。"},
            {
                "role": "user",
                "content": (
                    "用户消息：这个多少钱？\n"
                    "候选意图：product_price, product_stock\n"
                    "请从候选中选择，返回 JSON："
                    '{"primary_intent":"...","secondary_intents":[],"need_clarification":false,"reason":"..."}'
                ),
            },
        ],
        model=settings.AI_INTENT_JUDGE_MODEL,
        max_tokens=settings.AI_INTENT_JUDGE_MAX_TOKENS,
        temperature=0,
    )
    parsed = json.loads(result)
    print(f"\nparsed: {parsed}")

    assert parsed["primary_intent"] == "product_price"
    assert isinstance(parsed.get("secondary_intents"), list)


@pytest.mark.asyncio
async def test_chat_calls_configured_api_for_general_reply():
    """通用回复应真实调用当前配置的模型 API。"""
    client = LLMClient()
    result = await client.chat(
        [
            {"role": "system", "content": "你是一个简洁的中文客服助手。"},
            {"role": "user", "content": "你好，帮我简单介绍一下你能做什么。"},
        ],
        model=settings.AI_GENERAL_REPLY_MODEL,
        max_new_tokens=settings.AI_GENERAL_REPLY_MAX_TOKENS,
        temperature=0.2,
    )

    print(f"\nresult: {result}")
    assert result
    assert len(result) <= 300
