"""Phase 9 Agent 核心数据结构。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession


class ExecutionMode(str, Enum):
    DIRECT_SKILL = "direct_skill"
    AGENT_PLANNER = "agent_planner"
    CLARIFY = "clarify"
    HUMAN = "human"


@dataclass(frozen=True, slots=True)
class ToolResult:
    """工具调用返回结果。"""

    ok: bool
    skill_name: str
    result: Any = None
    error: str | None = None


class AgentState(TypedDict, total=False):
    """LangGraph Agent 状态 — TypedDict 让 LangGraph 正确推断频道。"""

    messages: list[dict[str, str]]
    tenant_id: int
    conversation_id: int
    contact_id: int | None
    execution_mode: str
    planned_tool_calls: list[dict]
    tool_results: list[dict]
    tool_call_count: int
    final_reply: str | None
    error: str | None


@dataclass
class AgentContext:
    """Agent 执行上下文，通过 LangGraph config.configurable 传递。

    DB session 不能序列化到 AgentState，必须通过 config 传入。
    """

    db: AsyncSession
    tenant_id: int
    conversation_id: int
    contact_id: int | None = None
