"""集成层 trace_id 透传测试：X-Trace-Id 请求头注入 + trace_id 日志。"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from app.common.trace.context import reset_trace_id, set_trace_id
from app.integrations.base import BaseClientError
from app.integrations.trace_headers import TRACE_HEADER_NAME, inject_trace_header


# ═══════════════════════════════════════════════════════════════════════
# inject_trace_header 单元测试
# ═══════════════════════════════════════════════════════════════════════


class TestInjectTraceHeader:
    def setup_method(self) -> None:
        reset_trace_id()

    def test_no_trace_id_returns_empty_dict(self) -> None:
        result = inject_trace_header(None)
        assert result == {}

    def test_no_trace_id_preserves_existing(self) -> None:
        result = inject_trace_header({"Content-Type": "application/json"})
        assert result == {"Content-Type": "application/json"}

    def test_injects_trace_id(self) -> None:
        set_trace_id("abcd1234efgh5678")
        result = inject_trace_header(None)
        assert result == {TRACE_HEADER_NAME: "abcd1234efgh5678"}

    def test_injects_trace_id_into_existing(self) -> None:
        set_trace_id("trace-001")
        result = inject_trace_header({"Content-Type": "application/json"})
        assert result["Content-Type"] == "application/json"
        assert result[TRACE_HEADER_NAME] == "trace-001"

    def test_does_not_overwrite_existing(self) -> None:
        set_trace_id("should-not-appear")
        result = inject_trace_header({TRACE_HEADER_NAME: "existing-trace"})
        assert result[TRACE_HEADER_NAME] == "existing-trace"

    def test_does_not_mutate_original(self) -> None:
        set_trace_id("trace-id")
        original: dict = {"Content-Type": "application/json"}
        result = inject_trace_header(original)
        assert TRACE_HEADER_NAME not in original
        assert TRACE_HEADER_NAME in result

    def test_empty_string_trace_id_no_inject(self) -> None:
        set_trace_id("")
        result = inject_trace_header(None)
        assert result == {}

    # ── 大小写不敏感 ──

    def test_does_not_overwrite_lowercase_header(self) -> None:
        set_trace_id("should-not-appear")
        result = inject_trace_header({"x-trace-id": "lowercase-trace"})
        assert result == {"x-trace-id": "lowercase-trace"}

    def test_does_not_overwrite_mixed_case_header(self) -> None:
        set_trace_id("should-not-appear")
        result = inject_trace_header({"X-Trace-Id": "original"})
        assert result["X-Trace-Id"] == "original"

    def test_preserves_original_case_when_skip(self) -> None:
        """已有小写 x-trace-id 时不注入也不将其标准化为 X-Trace-Id。"""
        set_trace_id("should-not-appear")
        result = inject_trace_header({"x-trace-id": "keep-case"})
        assert "X-Trace-Id" not in result
        assert result["x-trace-id"] == "keep-case"


# ═══════════════════════════════════════════════════════════════════════
# 辅助工具：创建 mock httpx 客户端上下文管理器
# ═══════════════════════════════════════════════════════════════════════


def _mock_http_client(method: str, response_data: dict, status_code: int = 200) -> AsyncMock:
    """创建 mock httpx.AsyncClient 实例，返回指定的 JSON 响应。

    Args:
        method: 要 mock 的 HTTP 方法 ('request', 'post', 'get')
        response_data: json.return_value 的值
        status_code: resp.status_code 的值（部分客户端检查此项）
    """
    mock_resp = Mock(spec=httpx.Response)
    mock_resp.status_code = status_code
    mock_resp.json.return_value = response_data
    mock_resp.content = str(response_data).encode() if response_data else b"{}"

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    method_mock = getattr(mock_client, method)
    method_mock.return_value = mock_resp
    mock_client.__aenter__.return_value = mock_client

    return mock_client


def _mock_http_client_with_side_effect(method: str) -> AsyncMock:
    """创建 mock httpx.AsyncClient，由调用方自行设置 side_effect 检查请求头。"""
    mock_resp = Mock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True}

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value = mock_client
    return mock_client


# ═══════════════════════════════════════════════════════════════════════
# BaseClient._request() trace header 验证
# ═══════════════════════════════════════════════════════════════════════


class TestBaseClientTraceHeader:
    """验证 BaseClient._request() 传递了 X-Trace-Id 请求头。"""

    def setup_method(self) -> None:
        reset_trace_id()

    async def test_injects_trace_header(self) -> None:
        """_request() 调用时携带 X-Trace-Id 请求头。"""
        from app.integrations.base import BaseClient

        mock_resp = Mock(spec=httpx.Response)
        mock_resp.json.return_value = {"ok": True}

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.request.return_value = mock_resp
        mock_client.__aenter__.return_value = mock_client

        client = BaseClient(base_url="http://localhost:9999", timeout_seconds=1)
        set_trace_id("baseclitest1234")

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await client._request("GET", "/test")

        assert result == {"ok": True}
        _, kwargs = mock_client.request.call_args
        headers = kwargs.get("headers", {})
        assert headers.get(TRACE_HEADER_NAME) == "baseclitest1234"


# ═══════════════════════════════════════════════════════════════════════
# BaseClient 异常处理验证
# ═══════════════════════════════════════════════════════════════════════


class TestBaseClientError:
    """验证 BaseClient._request() 的异常转换——httpx 异常必须转为 BaseClientError，不暴露 httpx 类型。"""

    def setup_method(self) -> None:
        reset_trace_id()

    async def test_connect_error_raises_base_client_error(self) -> None:
        """ConnectError 不会产生未捕获的 AttributeError，应转为 BaseClientError。"""
        from app.integrations.base import BaseClient

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.__aenter__.return_value = mock_client

        # ConnectError 没有 .response 属性，之前会因 getattr(exc.response, ...) 抛 AttributeError
        connect_error = httpx.ConnectError("connection refused")
        mock_client.request.side_effect = connect_error

        client = BaseClient(base_url="http://localhost:9999", timeout_seconds=1, max_retries=0)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(BaseClientError):
                await client._request("GET", "/test")


# ═══════════════════════════════════════════════════════════════════════
# LLMClient trace 验证
# ═══════════════════════════════════════════════════════════════════════


class TestLLMClientTrace:
    def setup_method(self) -> None:
        reset_trace_id()

    async def test_http_post_injects_trace_header(self) -> None:
        """_http_post 请求携带 X-Trace-Id 头。"""
        from app.integrations.llm_client import LLMClient

        mock_resp = Mock(spec=httpx.Response)
        mock_resp.json.return_value = {"choices": [{"message": {"content": "hello"}}]}

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.request.return_value = mock_resp
        mock_client.__aenter__.return_value = mock_client

        client = LLMClient(provider="http", base_url="http://localhost:9999", api_key="test")
        set_trace_id("llm-http-trace")

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await client._http_post("/v1/chat/completions", {"model": "test"})

        assert "hello" in str(result)
        _, kwargs = mock_client.request.call_args
        headers = kwargs.get("headers", {})
        assert headers.get(TRACE_HEADER_NAME) == "llm-http-trace"


# ═══════════════════════════════════════════════════════════════════════
# QdrantVectorClient trace 验证
# ═══════════════════════════════════════════════════════════════════════


class TestQdrantTrace:
    def setup_method(self) -> None:
        reset_trace_id()

    async def test_request_injects_trace_header(self) -> None:
        """_request 请求携带 X-Trace-Id 头。"""
        from app.integrations.qdrant_client import QdrantVectorClient

        mock_resp = Mock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.content = b'{"result": []}'
        mock_resp.json.return_value = {"result": []}

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.request.return_value = mock_resp
        mock_client.__aenter__.return_value = mock_client

        client = QdrantVectorClient(
            base_url="http://localhost:9999",
            api_key=None,
            timeout_seconds=1,
            vector_size=768,
        )
        set_trace_id("qdrant-trace")

        with (
            patch("app.config.settings.QDRANT_ENABLED", True),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            result = await client._request("GET", "/collections/test")

        assert isinstance(result, dict)
        _, kwargs = mock_client.request.call_args
        headers = kwargs.get("headers", {})
        assert headers.get(TRACE_HEADER_NAME) == "qdrant-trace"

    async def test_collection_exists_injects_trace_header(self) -> None:
        """_collection_exists 请求携带 X-Trace-Id 头。"""
        from app.integrations.qdrant_client import QdrantVectorClient

        mock_resp = Mock(spec=httpx.Response)
        mock_resp.status_code = 200

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.request.return_value = mock_resp
        mock_client.__aenter__.return_value = mock_client

        client = QdrantVectorClient(
            base_url="http://localhost:9999",
            api_key=None,
            timeout_seconds=1,
            vector_size=768,
        )
        set_trace_id("exists-trace")

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await client._collection_exists("test-collection")

        assert result is True
        _, kwargs = mock_client.request.call_args
        headers = kwargs.get("headers", {})
        assert headers.get(TRACE_HEADER_NAME) == "exists-trace"


# ═══════════════════════════════════════════════════════════════════════
# EmbeddingClient trace 验证
# ═══════════════════════════════════════════════════════════════════════


class TestEmbeddingTrace:
    def setup_method(self) -> None:
        reset_trace_id()

    async def test_post_json_injects_trace_header(self) -> None:
        """_post_json 请求携带 X-Trace-Id 头。"""
        from app.integrations.embedding_client import EmbeddingClient

        mock_resp = Mock(spec=httpx.Response)
        mock_resp.json.return_value = {"embeddings": [[0.1, 0.2, 0.3]]}

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.request.return_value = mock_resp
        mock_client.__aenter__.return_value = mock_client

        client = EmbeddingClient(base_url="http://localhost:9999", timeout_seconds=1)
        set_trace_id("embed-trace")

        with patch("httpx.AsyncClient", return_value=mock_client):
            data = await client._post_json("/embed", {"texts": ["hello"]})

        assert "embeddings" in data
        _, kwargs = mock_client.request.call_args
        headers = kwargs.get("headers", {})
        assert headers.get(TRACE_HEADER_NAME) == "embed-trace"


# ═══════════════════════════════════════════════════════════════════════
# RerankerClient trace 验证
# ═══════════════════════════════════════════════════════════════════════


class TestRerankerTrace:
    def setup_method(self) -> None:
        reset_trace_id()

    async def test_rerank_http_injects_trace_header(self) -> None:
        """_rerank_http 请求携带 X-Trace-Id 头。"""
        from app.integrations.reranker_client import RerankerClient

        mock_resp = Mock(spec=httpx.Response)
        mock_resp.json.return_value = {"results": [{"index": 0, "score": 0.9}]}

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.request.return_value = mock_resp
        mock_client.__aenter__.return_value = mock_client

        with (
            patch("app.config.settings.AI_RERANKER_PROVIDER", "http"),
            patch("app.config.settings.AI_RERANKER_ENABLED", True),
            patch("app.config.settings.AI_KNOWLEDGE_RERANK_TOP_K", 5),
        ):
            client = RerankerClient(base_url="http://localhost:9999", timeout_seconds=1)

        with patch("httpx.AsyncClient", return_value=mock_client):
            set_trace_id("rerank-trace-http")
            results = await client.rerank("query", ["doc1", "doc2"], top_k=2)

        assert len(results) == 1
        _, kwargs = mock_client.request.call_args
        headers = kwargs.get("headers", {})
        assert headers.get(TRACE_HEADER_NAME) == "rerank-trace-http"

    async def test_rerank_qwen_injects_trace_header(self) -> None:
        """_rerank_qwen 请求携带 X-Trace-Id 头。"""
        from app.integrations.reranker_client import RerankerClient

        mock_resp = Mock(spec=httpx.Response)
        mock_resp.json.return_value = {
            "output": {"results": [{"index": 0, "relevance_score": 0.95, "document": "doc1"}]}
        }

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.request.return_value = mock_resp
        mock_client.__aenter__.return_value = mock_client

        with (
            patch("app.config.settings.AI_RERANKER_PROVIDER", "qwen"),
            patch("app.config.settings.AI_RERANKER_ENABLED", True),
            patch("app.config.settings.AI_RERANKER_MODEL", "qwen-rerank"),
            patch("app.config.settings.AI_KNOWLEDGE_RERANK_TOP_K", 5),
        ):
            client = RerankerClient(base_url="http://localhost:9999", timeout_seconds=1)

        with patch("httpx.AsyncClient", return_value=mock_client):
            set_trace_id("rerank-trace-qwen")
            results = await client.rerank("query", ["doc1"], top_k=1)

        assert len(results) == 1
        _, kwargs = mock_client.request.call_args
        headers = kwargs.get("headers", {})
        assert headers.get(TRACE_HEADER_NAME) == "rerank-trace-qwen"


# ═══════════════════════════════════════════════════════════════════════
# WeComOutboundClient trace 验证
# ═══════════════════════════════════════════════════════════════════════


class TestWeComOutboundTrace:
    def setup_method(self) -> None:
        reset_trace_id()

    async def test_get_json_injects_trace_header(self) -> None:
        """_get_json 请求携带 X-Trace-Id 头。"""
        from app.integrations.wecom_outbound import WeComOutboundClient

        mock_resp = Mock(spec=httpx.Response)
        mock_resp.json.return_value = {"errcode": 0, "access_token": "token123"}

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.request.return_value = mock_resp
        mock_client.__aenter__.return_value = mock_client

        client = WeComOutboundClient({
            "corpid": "test",
            "corpsecret": "test",
            "agentid": "1000001",
        })

        with patch("httpx.AsyncClient", return_value=mock_client):
            set_trace_id("wecom-get-trace")
            data = await client._get_json("/cgi-bin/gettoken", {"corpid": "test", "corpsecret": "test"})

        assert data["access_token"] == "token123"
        _, kwargs = mock_client.request.call_args
        headers = kwargs.get("headers", {})
        assert headers.get(TRACE_HEADER_NAME) == "wecom-get-trace"

    async def test_post_json_injects_trace_header(self) -> None:
        """_post_json 请求携带 X-Trace-Id 头。"""
        from app.integrations.wecom_outbound import WeComOutboundClient

        mock_resp = Mock(spec=httpx.Response)
        mock_resp.json.return_value = {"errcode": 0, "errmsg": "ok"}

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.request.return_value = mock_resp
        mock_client.__aenter__.return_value = mock_client

        client = WeComOutboundClient({
            "corpid": "test",
            "corpsecret": "test",
            "agentid": "1000001",
        })

        with patch("httpx.AsyncClient", return_value=mock_client):
            set_trace_id("wecom-post-trace")
            data = await client._post_json("/cgi-bin/message/send", {"access_token": "tok"}, {"touser": "u"})

        assert data["errcode"] == 0
        _, kwargs = mock_client.request.call_args
        headers = kwargs.get("headers", {})
        assert headers.get(TRACE_HEADER_NAME) == "wecom-post-trace"
