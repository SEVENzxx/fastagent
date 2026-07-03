"""Graphs — 复杂多轮流程使用 LangGraph 子图。

只用于：下单、取消、售后等需要多轮交互的写操作。
顶层编排禁止使用 LangGraph，使用普通 async 函数。
"""

from __future__ import annotations

from app.ai.graphs.order_creation import build_order_creation_graph, get_creation_graph
from app.ai.graphs.order_cancel import build_order_cancel_graph, get_cancel_graph
from app.ai.graphs.order_refund import get_refund_graph

__all__ = [
    "build_order_creation_graph",
    "build_order_cancel_graph",
    "get_creation_graph",
    "get_cancel_graph",
    "get_refund_graph",
]


async def close_order_graph_checkpointers() -> None:
    """Redis checkpointer 无需显式关闭连接。"""
    pass
