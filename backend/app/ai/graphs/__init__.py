"""Graphs — 复杂多轮流程使用 LangGraph 子图。

只用于：下单、取消、售后等需要多轮交互的写操作。
顶层编排禁止使用 LangGraph，使用普通 async 函数。
"""

from __future__ import annotations

from app.ai.graphs.order_creation import (
    build_order_creation_graph,
    close_checkpointer as close_creation_checkpointer,
    get_creation_graph,
)
from app.ai.graphs.order_cancel import (
    build_order_cancel_graph,
    close_checkpointer as close_cancel_checkpointer,
    get_cancel_graph,
)

__all__ = [
    "build_order_creation_graph",
    "build_order_cancel_graph",
    "close_creation_checkpointer",
    "close_cancel_checkpointer",
    "get_creation_graph",
    "get_cancel_graph",
]


async def close_order_graph_checkpointers() -> None:
    """关闭所有 graph 的 SQLite checkpointer 连接。"""
    await close_creation_checkpointer()
    await close_cancel_checkpointer()
