"""Agent 包公开接口。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.ai.agent.graph import run_agent as run_agent


async def run_agent(*args, **kwargs):
    """延迟导入 graph 模块，避免子模块导入时加载所有 skill 依赖。"""
    from app.ai.agent.graph import run_agent as _run_agent

    return await _run_agent(*args, **kwargs)


__all__ = ["run_agent"]
