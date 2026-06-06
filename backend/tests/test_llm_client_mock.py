from unittest.mock import AsyncMock, patch
import sys
import types

import pytest

from app.integrations.llm_client import LLMClient, LLMClientError, LLMUseCase, normalize_litellm_model


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
async def test_general_reply_uses_short_timeout(monkeypatch):
    monkeypatch.setattr("app.integrations.llm_client.settings.AI_GENERAL_REPLY_TIMEOUT_SECONDS", 4.0)

    client = await LLMClient.for_use_case(LLMUseCase.GENERAL_REPLY, tenant_id=123)

    assert client.timeout_seconds == 4.0


@pytest.mark.asyncio
async def test_agent_use_case_loads_tenant_config():
    tenant_client = LLMClient(provider="litellm", base_url="", model="tenant-model")
    with patch.object(LLMClient, "_from_tenant", new=AsyncMock(return_value=tenant_client)) as from_tenant:
        client = await LLMClient.for_use_case(LLMUseCase.AGENT, tenant_id=123)

    assert client is tenant_client
    from_tenant.assert_awaited_once_with(123)


def test_qwen_model_is_normalized_for_dashscope_litellm():
    assert normalize_litellm_model("qwen-plus", "qwen") == "dashscope/qwen-plus"
    assert normalize_litellm_model("qwen3-plus", "dashscope") == "dashscope/qwen3-plus"
    assert normalize_litellm_model("qwen/qwen3.6-plus", "qwen") == "dashscope/qwen3.6-plus"
    assert normalize_litellm_model("qwen-plus", "litellm") == "dashscope/qwen-plus"


def test_explicit_openai_model_is_not_rewritten():
    assert normalize_litellm_model("openai/gpt-4o-mini", "openai") == "openai/gpt-4o-mini"
    assert normalize_litellm_model("ollama/llama3.1", "ollama") == "ollama/llama3.1"
    assert normalize_litellm_model("qwen2.5", "ollama") == "qwen2.5"


def test_llm_client_stores_normalized_model_for_qwen_provider():
    client = LLMClient(provider="qwen", base_url="", model="qwen3.6-plus")

    assert client.provider == "qwen"
    assert client.model == "dashscope/qwen3.6-plus"


@pytest.mark.asyncio
async def test_litellm_call_uses_normalized_dashscope_model(monkeypatch):
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(acompletion=fake_acompletion))
    client = LLMClient(
        provider="qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-test",
        model="qwen3.6-plus",
    )

    response = await client._litellm_call(
        [{"role": "user", "content": "hello"}],
        max_tokens=16,
        temperature=0.2,
        stream=False,
    )

    assert response["choices"][0]["message"]["content"] == "ok"
    assert captured["model"] == "dashscope/qwen3.6-plus"
    assert captured["api_base"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert captured["api_key"] == "sk-test"
    assert captured["max_retries"] == 0
    assert captured["num_retries"] == 0
