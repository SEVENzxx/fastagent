"""共享 LangGraph checkpointer 工厂 — 生产用 SQLite，测试用 MemorySaver。

所有操作型子图（下单、取消、售后）共享同一 SQLite 数据库文件，
利用 aiosqlite + AsyncSqliteSaver 提供 async 持久化。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_CHECKPOINTER_DIR = Path(__file__).resolve().parents[3] / "data" / "checkpoints"
_CHECKPOINTER = None


async def get_checkpointer() -> Any:
    """返回持久化 checkpointer。

    生产环境：AsyncSqliteSaver（基于 aiosqlite，持久化到 data/checkpoints/graphs.db）
    测试环境：MemorySaver（进程内，无需外部依赖）
    """
    global _CHECKPOINTER
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER

    if settings.FASTAGENT_TEST_MODE:
        from langgraph.checkpoint.memory import MemorySaver
        _CHECKPOINTER = MemorySaver()
        return _CHECKPOINTER

    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    _CHECKPOINTER_DIR.mkdir(parents=True, exist_ok=True)
    db_path = _CHECKPOINTER_DIR / "graphs.db"
    conn = await aiosqlite.connect(str(db_path))
    _CHECKPOINTER = AsyncSqliteSaver(conn)
    logger.info("SQLite checkpointer 已打开: %s", db_path)
    return _CHECKPOINTER


def reset_checkpointer() -> None:
    """重置 checkpointer 单例（测试用）。"""
    global _CHECKPOINTER
    _CHECKPOINTER = None
