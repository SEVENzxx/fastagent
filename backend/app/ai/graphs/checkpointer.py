"""共享 LangGraph checkpointer 工厂 — 生产用 MemorySaver，Redis 暂不可用。

当前 langgraph-checkpoint-redis v0.5.0 的 async 方法（aget_tuple、aput 等）
均为 NotImplementedError 空壳，无法在 async 图中使用。

临时回退到 MemorySaver，待上游修复后再切回 Redis。
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from app.config import settings

logger = logging.getLogger(__name__)

_CHECKPOINTER = None


async def get_checkpointer() -> Any:
    """返回持久化 checkpointer。

    生产环境／测试环境均使用 MemorySaver（async 接口完整）。
    """
    global _CHECKPOINTER
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER

    _CHECKPOINTER = MemorySaver()
    return _CHECKPOINTER


def reset_checkpointer() -> None:
    """重置 checkpointer 单例（测试用）。"""
    global _CHECKPOINTER
    _CHECKPOINTER = None
