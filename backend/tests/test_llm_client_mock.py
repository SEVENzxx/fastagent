from unittest.mock import AsyncMock, patch

import pytest

from app.integrations.llm_client import LLMClient, LLMClientError, LLMUseCase


@pytest.mark.asyncio
async def test_http_complete_uses_openai_compatible_endpoint():
    client = LLMClient(provider="http", base_url="http://llm.local", model="mock-model")
    client._http_post = AsyncMock(
        return_value={"choices": [{"message": {"content": " mock reply "}}]}
    )
    client._record_usage = AsyncMock()

    result = await client.complete(
        [{"role": "user", "content": "hello"}],
        max_tokens=32,
        temperature=0,
    )

    assert result == "mock reply"
    client._http_post.assert_awaited_once_with(
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


def test_extract_content_rejects_invalid_response():
    client = LLMClient(provider="http", base_url="http://llm.local", model="mock-model")

    with pytest.raises(LLMClientError):
        client._extract_content({"choices": []})


@pytest.mark.asyncio
async def test_local_use_case_does_not_load_tenant_config():
    with patch.object(LLMClient, "_from_tenant", new_callable=AsyncMock) as from_tenant:
        client = await LLMClient.for_use_case(LLMUseCase.GENERAL_REPLY, tenant_id=123)

    assert client.model
    from_tenant.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_use_case_loads_tenant_config():
    tenant_client = LLMClient(provider="litellm", base_url="", model="tenant-model")
    with patch.object(LLMClient, "_from_tenant", new=AsyncMock(return_value=tenant_client)) as from_tenant:
        client = await LLMClient.for_use_case(LLMUseCase.AGENT, tenant_id=123)

    assert client is tenant_client
    from_tenant.assert_awaited_once_with(123)
