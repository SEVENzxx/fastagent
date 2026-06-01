from unittest.mock import AsyncMock

import pytest

from app.integrations.llm_client import LLMClient, LLMClientError


@pytest.mark.asyncio
async def test_http_complete_uses_openai_compatible_endpoint():
    client = LLMClient(provider="http", base_url="http://llm.local", model="mock-model")
    client._http_post_json = AsyncMock(
        return_value={"choices": [{"message": {"content": " mock reply "}}]}
    )
    client._record_usage = AsyncMock()

    result = await client.complete(
        [{"role": "user", "content": "hello"}],
        max_tokens=32,
        temperature=0,
    )

    assert result == "mock reply"
    client._http_post_json.assert_awaited_once_with(
        "/v1/chat/completions",
        {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 32,
            "temperature": 0,
        },
    )
    client._record_usage.assert_awaited_once()


@pytest.mark.asyncio
async def test_http_stream_falls_back_to_single_completion():
    client = LLMClient(provider="http", base_url="http://llm.local", model="mock-model")
    client.complete = AsyncMock(return_value="one chunk")

    chunks = [chunk async for chunk in client.stream([{"role": "user", "content": "hello"}])]

    assert chunks == ["one chunk"]
    client.complete.assert_awaited_once()


def test_extract_message_content_rejects_invalid_provider_response():
    client = LLMClient(provider="http", base_url="http://llm.local", model="mock-model")

    with pytest.raises(LLMClientError):
        client._extract_message_content({"choices": []})
