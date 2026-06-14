"""LangFuse 可观测性辅助工具和结构化时序日志。"""

from __future__ import annotations

import logging
import os
import time
from contextlib import AbstractContextManager, asynccontextmanager, nullcontext
from contextvars import ContextVar
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)
_ACTIVE_TRACE_CONTEXT: ContextVar[dict[str, str] | None] = ContextVar(
    "fastagent_langfuse_trace_context",
    default=None,
)


REPLY_SOURCE_PRODUCT_SEARCH_TEMPLATE = "product.search.template"
REPLY_SOURCE_PRODUCT_DETAIL_TEMPLATE = "product.detail.template"
REPLY_SOURCE_PRODUCT_QA_LLM = "product.qa.llm"
REPLY_SOURCE_PRODUCT_COMPARE_LLM = "product.compare.llm"
REPLY_SOURCE_PRODUCT_CLARIFY = "product.clarify"

REPLY_SOURCE_ORDER_QUERY = "order.query"
REPLY_SOURCE_ORDER_CREATE = "order.create"
REPLY_SOURCE_ORDER_CONFIRM = "order.confirm"

REPLY_SOURCE_RAG_LLM_SYNTHESIS = "rag.llm_synthesis"
REPLY_SOURCE_RAG_EXACT_MATCH = "rag.exact_match"

REPLY_SOURCE_TEMPLATE_FIXED = "template.fixed"
REPLY_SOURCE_HUMAN_HANDOFF = "human.handoff"
REPLY_SOURCE_FALLBACK_LLM = "fallback.llm"


@asynccontextmanager
async def observe_span(name: str, *, input_data: Any | None = None, **metadata: Any):
    """创建一个子观测 span，并始终记录时序日志。"""
    async with _observe(
        name=name,
        as_type="span",
        log_label="observe_span",
        metadata=metadata,
        input_data=input_data,
        require_parent=True,
    ) as observation:
        yield observation


@asynccontextmanager
async def observe_trace(
    name: str,
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    tags: list[str] | None = None,
    input_data: Any | None = None,
    **metadata: Any,
):
    """为一次用户请求创建唯一的根 trace。"""
    async with _observe(
        name=name,
        as_type="span",
        log_label="observe_trace",
        metadata=metadata,
        input_data=input_data,
        force_new_trace=True,
        trace_name=name,
        user_id=user_id,
        session_id=session_id,
        tags=tags,
    ) as observation:
        yield observation


# 后向兼容别名，供现有业务代码使用。
trace_step = observe_span


@asynccontextmanager
async def observe_llm_call(
    model: str,
    provider: str = "",
    *,
    input_data: Any | None = None,
    **metadata: Any,
):
    """为 LLM 调用创建 LangFuse generation 观测。"""
    async with _observe(
        name="llm.complete",
        as_type="generation",
        log_label="observe_llm_call",
        metadata={"provider": provider or "unknown", **metadata},
        input_data=input_data,
        model=model,
        model_parameters={
            key: value
            for key, value in metadata.items()
            if key in {"max_tokens", "temperature", "stream"}
        },
        require_parent=True,
    ) as observation:
        yield observation


@asynccontextmanager
async def observe_db_call(
    db_type: str,
    operation: str,
    *,
    input_data: Any | None = None,
    **metadata: Any,
):
    """创建 DB/缓存观测。"""
    async with _observe(
        name=f"{db_type}.{operation}",
        as_type="span",
        log_label="observe_db_call",
        metadata={"db_type": db_type, "operation": operation, **metadata},
        input_data=input_data,
        require_parent=True,
    ) as observation:
        yield observation


@asynccontextmanager
async def observe_vector_call(
    collection: str,
    operation: str,
    *,
    input_data: Any | None = None,
    **metadata: Any,
):
    """创建向量检索/写入观测。"""
    async with _observe(
        name=f"vector.{operation}",
        as_type="retriever" if operation == "search" else "span",
        log_label="observe_vector_call",
        metadata={"collection": collection, "operation": operation, **metadata},
        input_data=input_data,
        require_parent=True,
    ) as observation:
        yield observation


@asynccontextmanager
async def observe_external_http(
    service: str,
    method: str,
    url: str,
    *,
    input_data: Any | None = None,
    **metadata: Any,
):
    """为外部 HTTP 依赖调用创建观测。"""
    safe_url = _safe_url(url)
    async with _observe(
        name=f"http.{service}",
        as_type="embedding" if service == "embedding" else "span",
        log_label="observe_external_http",
        metadata={"service": service, "method": method, "url": safe_url, **metadata},
        input_data=input_data,
        require_parent=True,
    ) as observation:
        yield observation


@asynccontextmanager
async def _observe(
    *,
    name: str,
    as_type: str,
    log_label: str,
    metadata: dict[str, Any],
    input_data: Any | None = None,
    model: str | None = None,
    model_parameters: dict[str, Any] | None = None,
    require_parent: bool = False,
    force_new_trace: bool = False,
    trace_name: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    tags: list[str] | None = None,
):
    """在 tracing 激活时创建 LangFuse 子观测，并始终记录时序日志。"""
    start = time.perf_counter()
    log_meta = _sanitize_meta(metadata)
    manager = _start_langfuse_observation(
        name=name,
        as_type=as_type,
        metadata=log_meta,
        input_data=input_data,
        model=model,
        model_parameters=model_parameters,
        require_parent=require_parent,
        force_new_trace=force_new_trace,
    )
    observation = None
    token = None
    try:
        if manager is None:
            yield None
        else:
            with manager as observation:
                propagation = _start_langfuse_propagation(
                    trace_name=trace_name,
                    user_id=user_id,
                    session_id=session_id,
                    tags=tags,
                    metadata=metadata if trace_name else None,
                )
                with propagation:
                    active_context = _read_current_langfuse_trace_context()
                    if active_context:
                        token = _ACTIVE_TRACE_CONTEXT.set(active_context)
                    try:
                        yield observation
                    finally:
                        if token is not None:
                            _ACTIVE_TRACE_CONTEXT.reset(token)
    except Exception as exc:
        _mark_observation_error(observation, exc)
        raise
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s  name=%s  type=%s  duration_ms=%.1f  %s",
            log_label,
            name,
            as_type,
            elapsed_ms,
            "  ".join(f"{key}={value}" for key, value in log_meta.items()),
        )


def _start_langfuse_observation(
    *,
    name: str,
    as_type: str,
    metadata: dict[str, Any],
    input_data: Any | None,
    model: str | None,
    model_parameters: dict[str, Any] | None,
    require_parent: bool,
    force_new_trace: bool,
) -> AbstractContextManager[Any] | None:
    if not settings.LANGFUSE_ENABLED:
        return None
    if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        return None
    _inject_langfuse_env()
    try:
        from langfuse import get_client

        client = get_client()
        kwargs: dict[str, Any] = {
            "name": name,
            "as_type": as_type,
            "metadata": sanitize_for_trace(metadata),
            "end_on_exit": True,
        }
        if input_data is not None:
            kwargs["input"] = sanitize_for_trace(input_data)
        if model:
            kwargs["model"] = model
        if model_parameters:
            kwargs["model_parameters"] = sanitize_for_trace(model_parameters)
        if force_new_trace:
            kwargs["trace_context"] = {"trace_id": client.create_trace_id()}
        else:
            trace_context = _current_langfuse_trace_context(client)
            if require_parent and not trace_context:
                return None
            if trace_context:
                kwargs["trace_context"] = trace_context
        return client.start_as_current_observation(**kwargs)
    except Exception as exc:
        logger.debug("LangFuse 观测已跳过: name=%s error=%s", name, exc)
        return None


def _mark_observation_error(observation: Any, exc: Exception) -> None:
    if observation is None:
        return
    try:
        observation.update(level="ERROR", status_message=str(exc)[:500])
    except Exception:
        pass


def set_observation_io(
    observation: Any,
    *,
    input_data: Any | None = None,
    output_data: Any | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """尽力更新观测的 input/output，用于 LangFuse UI 展示。"""
    if observation is None:
        return
    payload: dict[str, Any] = {}
    if input_data is not None:
        payload["input"] = sanitize_for_trace(input_data)
    if output_data is not None:
        payload["output"] = sanitize_for_trace(output_data)
    if metadata:
        payload["metadata"] = sanitize_for_trace(metadata)
    if not payload:
        return
    try:
        observation.update(**payload)
    except Exception:
        pass


def _current_langfuse_trace_context(client: Any) -> dict[str, str] | None:
    """在有可用的活跃 LangFuse trace 时，将手动观测附加到其上。"""
    active_context = _ACTIVE_TRACE_CONTEXT.get()
    if active_context:
        return dict(active_context)
    return _read_current_langfuse_trace_context(client)


def _read_current_langfuse_trace_context(client: Any | None = None) -> dict[str, str] | None:
    """从 SDK/OpenTelemetry 上下文中读取当前活跃的 LangFuse 上下文。"""
    try:
        if client is None:
            from langfuse import get_client

            client = get_client()
        trace_id = client.get_current_trace_id()
        observation_id = client.get_current_observation_id()
    except Exception:
        return None
    if not trace_id:
        return None
    trace_context = {"trace_id": trace_id}
    if observation_id:
        trace_context["parent_span_id"] = observation_id
    return trace_context


def _start_langfuse_propagation(
    *,
    trace_name: str | None,
    user_id: str | None,
    session_id: str | None,
    tags: list[str] | None,
    metadata: dict[str, Any] | None,
) -> AbstractContextManager[Any]:
    if not any([trace_name, user_id, session_id, tags, metadata]):
        return nullcontext()
    try:
        from langfuse import propagate_attributes

        return propagate_attributes(
            trace_name=trace_name,
            user_id=user_id,
            session_id=session_id,
            tags=tags,
            metadata=_trace_attribute_metadata(metadata or {}),
        )
    except Exception as exc:
        logger.debug("LangFuse 传播已跳过: error=%s", exc)
        return nullcontext()


def _trace_attribute_metadata(metadata: dict[str, Any]) -> dict[str, str]:
    return {
        str(key): str(value)[:500]
        for key, value in metadata.items()
        if value is not None and isinstance(value, (str, int, float, bool))
    }


def _inject_langfuse_env() -> None:
    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.LANGFUSE_PUBLIC_KEY
    os.environ["LANGFUSE_SECRET_KEY"] = settings.LANGFUSE_SECRET_KEY
    os.environ["LANGFUSE_BASE_URL"] = settings.LANGFUSE_BASE_URL


def _safe_url(url: str) -> str:
    return str(url or "").split("?", 1)[0]


def begin_sql_observation(statement: str) -> dict[str, Any]:
    """从 SQLAlchemy 事件钩子启动同步 SQL 观测。"""
    operation = _sql_operation(statement)
    metadata = {
        "db_type": "postgresql",
        "operation": operation,
        "statement": _compact_sql(statement),
    }
    manager = _start_langfuse_observation(
        name=f"postgresql.{operation.lower()}",
        as_type="span",
        metadata=metadata,
        input_data={"operation": operation, "statement": metadata["statement"]},
        model=None,
        model_parameters=None,
        require_parent=True,
        force_new_trace=False,
    )
    observation = None
    if manager is not None:
        try:
            observation = manager.__enter__()
        except Exception as exc:
            logger.debug("SQL LangFuse 观测已跳过: error=%s", exc)
            manager = None
    return {
        "started": time.perf_counter(),
        "manager": manager,
        "observation": observation,
        "metadata": metadata,
    }


def end_sql_observation(
    handle: dict[str, Any] | None,
    *,
    rowcount: int | None = None,
    error: Exception | None = None,
) -> None:
    """结束由 begin_sql_observation 创建的 SQL 观测。"""
    if not handle:
        return
    elapsed_ms = (time.perf_counter() - float(handle.get("started", time.perf_counter()))) * 1000
    metadata = dict(handle.get("metadata") or {})
    if rowcount is not None and rowcount >= 0:
        metadata["rowcount"] = rowcount
    metadata["duration_ms"] = round(elapsed_ms, 1)
    observation = handle.get("observation")
    manager = handle.get("manager")
    if error is not None:
        _mark_observation_error(observation, error)
        metadata["error"] = str(error)[:300]
    if observation is not None:
        try:
            observation.update(
                metadata=sanitize_for_trace(metadata),
                output=sanitize_for_trace({
                    "rowcount": rowcount if rowcount is not None and rowcount >= 0 else None,
                    "duration_ms": metadata["duration_ms"],
                    "error": metadata.get("error"),
                }),
            )
        except Exception:
            pass
    if manager is not None:
        try:
            manager.__exit__(type(error) if error else None, error, getattr(error, "__traceback__", None))
        except Exception:
            pass
    logger.info(
        "observe_db_call  name=postgresql.%s  type=span  duration_ms=%.1f  rowcount=%s",
        str(metadata.get("operation", "query")).lower(),
        elapsed_ms,
        rowcount,
    )


def _sql_operation(statement: str) -> str:
    text = str(statement or "").lstrip()
    if not text:
        return "QUERY"
    return text.split(None, 1)[0].upper()


def _compact_sql(statement: str) -> str:
    return " ".join(str(statement or "").split())[:500]


def sanitize_for_trace(data: Any, max_str_len: int = 500) -> Any:
    """递归截断字符串和大容器，确保发送到 trace 的数据不会过大。"""
    if isinstance(data, str):
        return data[:max_str_len] + "..." if len(data) > max_str_len else data
    if isinstance(data, dict):
        return {key: sanitize_for_trace(value, max_str_len) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        limit = 20
        items = [sanitize_for_trace(item, max_str_len) for item in data[:limit]]
        if len(data) > limit:
            items.append(f"... {len(data) - limit} more")
        return items
    return data


def _sanitize_meta(meta: dict[str, Any]) -> dict[str, Any]:
    excluded = {"prompt", "messages", "full_payload", "body", "payload", "vector"}
    return {
        key: sanitize_for_trace(value)
        for key, value in meta.items()
        if key not in excluded
    }


def summarize_state(state: dict[str, Any]) -> dict[str, Any]:
    """从完整的 AssistantRuntimeState 中提取精简 trace 摘要。"""
    intent = state.get("intent_decision") or {}
    workflow = state.get("workflow_result") or {}
    tool_results = state.get("tool_results") or []

    product_count, top_ids = _extract_product_summary(tool_results)
    cost_level = workflow.get("cost_level", "")
    used_llm = (
        cost_level in ("HIGH_LLM",)
        or bool(workflow.get("used_llm"))
        or any(bool((item.get("result") or {}).get("used_llm")) for item in tool_results)
    )

    return {
        "input_text": (state.get("input_text") or "")[:100],
        "tenant_id": state.get("tenant_id"),
        "conversation_id": state.get("conversation_id"),
        "intent": intent.get("intent"),
        "skill": intent.get("skill"),
        "route_source": intent.get("source") or intent.get("intent_source"),
        "reply_source": workflow.get("reply_source"),
        "response_type": workflow.get("response_type"),
        "cost_level": cost_level,
        "used_llm": used_llm,
        "used_vector": _any_vector_used(tool_results),
        "used_db": _any_db_used(cost_level),
        "tool_names": [item.get("skill_name") for item in tool_results if item.get("skill_name")],
        "product_count": product_count,
        "top_product_ids": top_ids,
        "reply_len": len(workflow.get("text", state.get("reply", ""))),
    }


def _extract_product_summary(tool_results: list[dict[str, Any]]) -> tuple[int, list[str]]:
    for item in tool_results:
        if item.get("ok") and item.get("skill_name") == "search_products":
            products = item.get("result", {}).get("products", [])
            if products:
                return len(products), [
                    str(product.get("id", ""))
                    for product in products[:5]
                    if product.get("id")
                ]
    return 0, []


def _any_vector_used(tool_results: list[dict[str, Any]]) -> bool:
    for item in tool_results:
        result = item.get("result", {})
        if result.get("used_vector") or result.get("vector_search") or result.get("qdrant"):
            return True
        mode = result.get("mode", "")
        if "vector" in mode or "qdrant" in mode:
            return True
    return False


def _any_db_used(cost_level: str) -> bool:
    return cost_level in ("FREE_DB", "LOW_QA", "HIGH_LLM")


def get_langfuse_callback() -> object | None:
    """在配置启用时创建 LangFuse 的 LangChain 回调处理器。"""
    if not settings.LANGFUSE_ENABLED:
        return None
    if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        logger.info("LangFuse 密钥未配置；可观测性回调已禁用")
        return None

    _inject_langfuse_env()

    try:
        from langfuse.langchain import CallbackHandler
    except ImportError:
        logger.warning("langfuse 未安装；跳过 LangFuse 回调")
        return None

    logger.info("LangFuse 回调已启用: base_url=%s", settings.LANGFUSE_BASE_URL)
    return CallbackHandler()
