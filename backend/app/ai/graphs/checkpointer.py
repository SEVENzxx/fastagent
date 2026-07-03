"""共享 LangGraph checkpointer 工厂 — 生产用 Redis，测试用 MemorySaver。

所有操作型子图（下单、取消、售后）使用同一 Redis checkpointer 实例，
利用已有的 Redis 基础设施，避免 SQLite 文件管理和额外依赖。
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_CHECKPOINTER = None


async def get_checkpointer() -> Any:
    """返回持久化 checkpointer。

    生产环境：RedisSaver（基于已有 Redis 基础设施）
    测试环境：MemorySaver（进程内，无需外部依赖）
    """
    global _CHECKPOINTER
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER

    if settings.FASTAGENT_TEST_MODE:
        from langgraph.checkpoint.memory import MemorySaver
        _CHECKPOINTER = MemorySaver()
        return _CHECKPOINTER

    from langgraph.checkpoint.redis import RedisSaver

    # 使用 DB 1 避免与主应用缓存（DB 0）冲突
    redis_url = settings.REDIS_URL
    if redis_url.endswith("/0"):
        redis_url = redis_url[:-2] + "/1"

    _CHECKPOINTER = RedisSaver(redis_url=redis_url)
    return _CHECKPOINTER


def reset_checkpointer() -> None:
    """重置 checkpointer 单例（测试用）。"""
    global _CHECKPOINTER
    _CHECKPOINTER = None
