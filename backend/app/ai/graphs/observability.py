"""LangGraph 子图可观测性辅助。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from functools import wraps
from types import TracebackType
from typing import Any

from app.ai.observability import observe_span, set_observation_io

try:
    from langgraph.errors import GraphInterrupt
except Exception:  # pragma: no cover - 兼容不同 LangGraph 版本
    GraphInterrupt = None  # type: ignore[assignment]


_SAFE_KEYS = {
    "tenant_id",
    "conversation_id",
    "contact_id",
    "scenario_id",
    "graph_thread_id",
    "selected_product_id",
    "product_id",
    "product_name",
    "product_price",
    "quantity",
    "total_amount",
    "order_id",
    "selected_order_id",
    "selected_order_status",
    "cancelable",
    "refundable",
    "product_confirmed",
    "confirmed",
    "write_executed",
    "payment_status",
    "shipping_status",
    "cancel_reason",
    "refund_reason",
    "error",
}
_PRESENCE_ONLY_KEYS = {
    "input_text",
    "raw_text",
    "message",
    "shipping_address",
    "address",
    "receiver_phone",
    "phone",
    "mobile",
    "contact_phone",
    "receiver_name",
    "contact_name",
}
_PREVIEW_KEYS = {"reply"}


def observe_graph_node(
    graph_name: str,
    node_name: str,
    fn: Callable[..., Awaitable[dict[str, Any]]],
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """包装图节点，在 LangFuse 中记录节点耗时、输出摘要和正常中断。"""

    @wraps(fn)
    async def wrapped(state: Any, config: Any = None) -> dict[str, Any]:
        interrupt_exc: Exception | None = None
        interrupt_tb: TracebackType | None = None
        metadata = {
            "graph": graph_name,
            "graph_node": node_name,
            **_config_summary(config),
        }

        async with observe_span(
            f"langgraph.{graph_name}.{node_name}",
            input_data={"state": summarize_graph_payload(state)},
            **metadata,
        ) as observation:
            try:
                result = await fn(state, config)
            except Exception as exc:
                if not _is_graph_interrupt(exc):
                    raise
                interrupt_exc = exc
                interrupt_tb = exc.__traceback__
                # interrupt 是图的正常暂停，不应该在 LangFuse 中标成 ERROR。
                set_observation_io(
                    observation,
                    output_data={"status": "interrupted"},
                    metadata={**metadata, "status": "interrupted"},
                )
            else:
                set_observation_io(
                    observation,
                    output_data={
                        "status": "completed",
                        "updates": summarize_graph_payload(result),
                    },
                    metadata={**metadata, "status": "completed"},
                )
                return result

        if interrupt_exc is not None:
            raise interrupt_exc.with_traceback(interrupt_tb)
        return {}

    return wrapped


def graph_run_input_summary(
    *,
    scenario_id: str,
    graph_thread_id: str,
    initial_state: Mapping[str, Any] | None,
    resume_message: str | None,
) -> dict[str, Any]:
    """生成图运行入口的安全 input 摘要。"""
    return {
        "scenario_id": scenario_id,
        "graph_thread_id": graph_thread_id,
        "resume": resume_message is not None,
        "resume_len": len(resume_message or ""),
        "initial_state": summarize_graph_payload(initial_state) if initial_state else None,
    }


def graph_run_output_summary(result: Any, snapshot: Any) -> dict[str, Any]:
    """生成图运行完成后的安全 output 摘要。"""
    return {
        "result": summarize_graph_payload(result),
        "checkpoint": graph_snapshot_summary(snapshot),
    }


def graph_snapshot_summary(snapshot: Any) -> dict[str, Any]:
    """提取当前 checkpoint 的中断位置和状态摘要。"""
    next_nodes = list(getattr(snapshot, "next", ()) or ())
    interrupts = list(getattr(snapshot, "interrupts", ()) or ())
    values = getattr(snapshot, "values", None)
    summary: dict[str, Any] = {
        "interrupted": bool(next_nodes),
        "next_nodes": next_nodes,
        "interrupt_count": len(interrupts),
    }
    if interrupts:
        first_interrupt = interrupts[0]
        summary["interrupt_id"] = str(getattr(first_interrupt, "id", ""))
        summary["interrupt_value_preview"] = _preview(getattr(first_interrupt, "value", ""))
    if isinstance(values, Mapping):
        summary["state"] = summarize_graph_payload(values)
    return summary


def graph_snapshot_metadata(snapshot: Any) -> dict[str, Any]:
    """生成适合放在 LangFuse metadata 的 checkpoint 摘要。"""
    next_nodes = list(getattr(snapshot, "next", ()) or ())
    interrupts = list(getattr(snapshot, "interrupts", ()) or ())
    return {
        "interrupted": bool(next_nodes),
        "next_nodes": ",".join(str(node) for node in next_nodes),
        "interrupt_count": len(interrupts),
    }


def summarize_graph_payload(payload: Any) -> dict[str, Any]:
    """只保留调试需要的字段，避免把地址、电话、原始输入写入 trace。"""
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        return {"type": type(payload).__name__}

    summary: dict[str, Any] = {
        "keys": sorted(str(key) for key in payload.keys()),
    }
    for key, value in payload.items():
        key_str = str(key)
        if key_str in _SAFE_KEYS:
            summary[key_str] = _safe_value(value)
        elif key_str in _PREVIEW_KEYS:
            summary[f"{key_str}_preview"] = _preview(value)
        elif key_str in _PRESENCE_ONLY_KEYS:
            summary[f"has_{key_str}"] = bool(value)
            if key_str in {"input_text", "raw_text", "message"}:
                summary[f"{key_str}_len"] = len(str(value or ""))
        elif key_str == "idempotency_key":
            summary["has_idempotency_key"] = bool(value)
            summary["idempotency_key_prefix"] = str(value)[:24] if value else ""
        elif key_str in {"resolved_products", "orders"} and isinstance(value, list):
            summary[f"{key_str}_count"] = len(value)
        elif key_str == "collected_slots" and isinstance(value, (list, tuple, set)):
            summary[key_str] = sorted(str(item) for item in value)
    return summary


def _config_summary(config: Any) -> dict[str, Any]:
    if not isinstance(config, Mapping):
        return {}
    configurable = config.get("configurable") or {}
    if not isinstance(configurable, Mapping):
        return {}
    return {
        "thread_id": configurable.get("thread_id"),
        "auto_approve": configurable.get("auto_approve"),
        "has_db": configurable.get("db") is not None,
        "has_order_skill": configurable.get("order_skill") is not None,
    }


def _safe_value(value: Any) -> Any:
    if isinstance(value, str):
        return _preview(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(item) for item in list(value)[:10]]
    if isinstance(value, Mapping):
        return summarize_graph_payload(value)
    return str(value)[:120]


def _preview(value: Any, limit: int = 160) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _is_graph_interrupt(exc: Exception) -> bool:
    if GraphInterrupt is not None and isinstance(exc, GraphInterrupt):
        return True
    return exc.__class__.__name__ == "GraphInterrupt"
