"""Phase 9 Agent StateGraph — 7 节点编排。

流程：
  build_context → decide_execution_mode → plan_tools → dispatch_tools
  → generate_reply → post_process → END

CLARIFY 模式跳过 plan_tools 和 dispatch_tools。
"""

from __future__ import annotations

import logging

from langgraph.graph import END, StateGraph

from app.services.ai.agent.nodes import (
    build_context,
    decide_execution_mode,
    dispatch_tools,
    generate_reply,
    plan_tools_from_routed_intent,
    post_process,
)
from app.services.ai.agent.types import AgentContext, AgentState, ExecutionMode
from app.services.ai.intent.types import RoutedIntent

logger = logging.getLogger(__name__)


def _route_after_decide(state: AgentState) -> str:
    """decide_execution_mode 之后的边路由。

    DIRECT_SKILL / AGENT_PLANNER → plan_tools
    CLARIFY → generate_reply（跳过工具规划与调度）
    """
    if state.get("execution_mode") == ExecutionMode.CLARIFY.value:
        logger.info("[graph] CLARIFY → 跳过 plan/dispatch，直接 generate_reply")
        return "generate_reply"
    return "plan_tools_from_routed_intent"


def build_agent_graph() -> StateGraph:
    """构造并编译 Agent StateGraph。"""
    builder = StateGraph(AgentState)

    # 添加节点
    builder.add_node("build_context", build_context)
    builder.add_node("decide_execution_mode", decide_execution_mode)
    builder.add_node("plan_tools_from_routed_intent", plan_tools_from_routed_intent)
    builder.add_node("dispatch_tools", dispatch_tools)
    builder.add_node("generate_reply", generate_reply)
    builder.add_node("post_process", post_process)

    # 设置入口
    builder.set_entry_point("build_context")

    # 固定边
    builder.add_edge("build_context", "decide_execution_mode")

    # 条件路由：根据 execution_mode 决定下一步
    builder.add_conditional_edges(
        "decide_execution_mode",
        _route_after_decide,
        {
            "plan_tools_from_routed_intent": "plan_tools_from_routed_intent",
            "generate_reply": "generate_reply",
        },
    )

    builder.add_edge("plan_tools_from_routed_intent", "dispatch_tools")
    builder.add_edge("dispatch_tools", "generate_reply")
    builder.add_edge("generate_reply", "post_process")
    builder.add_edge("post_process", END)

    return builder.compile()


# 模块级编译实例（单进程复用）
_agent_graph = build_agent_graph()


async def run_agent(ctx: AgentContext, routed_intent: RoutedIntent) -> dict:
    """执行 Agent 图，返回 {"reply": str, "tool_results": list[dict]}。

    这是外部调用的主入口。
    """
    config = {
        "configurable": {
            "agent_context": ctx,
            "routed_intent": routed_intent,
        }
    }
    logger.info(
        "[graph] 开始执行：tenant_id=%s conversation_id=%s intent=%s route=%s",
        ctx.tenant_id,
        ctx.conversation_id,
        routed_intent.primary_intent,
        routed_intent.route,
    )
    result = await _agent_graph.ainvoke({}, config=config)
    reply = result.get("final_reply", "") or ""
    tool_results = result.get("tool_results", [])
    logger.info(
        "[graph] 执行完成：mode=%s reply_len=%s tool_calls=%s error=%s",
        result.get("execution_mode"),
        len(reply),
        result.get("tool_call_count"),
        result.get("error"),
    )
    return {"reply": reply, "tool_results": tool_results}
