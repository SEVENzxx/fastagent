"""Agent 子图编排（7 节点 + 1 条件路由）。

流程：
build_context（上下文注入） → decide_execution_mode（置信度门控）
→ [条件：CLARIFY 则跳过工具执行] → plan_tools_from_routed_intent（技能规划）
→ normalize_planned_tool_arguments（参数抽取+校验） → dispatch_tools（技能执行）
→ generate_reply（LLM 生成回复） → post_process（格式清洗） → END
"""

from __future__ import annotations

import logging

from langgraph.graph import END, StateGraph

from app.ai.agent.nodes import (
    build_context,
    decide_execution_mode,
    dispatch_tools,
    generate_reply,
    normalize_planned_tool_arguments,
    plan_tools_from_routed_intent,
    post_process,
)
from app.ai.agent.types import AgentContext, AgentState, ExecutionMode
from app.ai.classifier.types import RoutedIntent

logger = logging.getLogger(__name__)


def _route_after_decide(state: AgentState) -> str:
    """decide_execution_mode 后的条件边：
    CLARIFY → 直接 generate_reply（澄清追问，无需调工具）
    其余   → plan_tools_from_routed_intent
    """
    if state.get("execution_mode") == ExecutionMode.CLARIFY.value:
        return "generate_reply"
    return "plan_tools_from_routed_intent"


def build_agent_graph() -> StateGraph:
    """构造并编译 Agent StateGraph（模块加载时一次性编译）。"""

    builder = StateGraph(AgentState)

    # 注册 7 个节点
    builder.add_node("build_context", build_context)                                        # 初始化 AgentState
    builder.add_node("decide_execution_mode", decide_execution_mode)                        # 置信度门控
    builder.add_node("plan_tools_from_routed_intent", plan_tools_from_routed_intent)        # 技能规划
    builder.add_node("normalize_planned_tool_arguments", normalize_planned_tool_arguments)  # 参数抽取+校验
    builder.add_node("dispatch_tools", dispatch_tools)                                      # 技能执行
    builder.add_node("generate_reply", generate_reply)                                      # LLM 生成回复
    builder.add_node("post_process", post_process)                                          # 格式清洗

    # ── 边 ──
    builder.set_entry_point("build_context")
    builder.add_edge("build_context", "decide_execution_mode")
    # 置信度门控：低置信度 → CLARIFY 直奔 generate_reply，跳过工具调用
    builder.add_conditional_edges(
        "decide_execution_mode",
        _route_after_decide,
        {
            "plan_tools_from_routed_intent": "plan_tools_from_routed_intent",
            "generate_reply": "generate_reply",
        },
    )
    builder.add_edge("plan_tools_from_routed_intent", "normalize_planned_tool_arguments")
    builder.add_edge("normalize_planned_tool_arguments", "dispatch_tools")
    builder.add_edge("dispatch_tools", "generate_reply")
    builder.add_edge("generate_reply", "post_process")
    builder.add_edge("post_process", END)

    return builder.compile()


# ── 模块级单例（编译一次，全进程复用）──
_agent_graph = build_agent_graph()


async def run_agent(ctx: AgentContext, routed_intent: RoutedIntent) -> dict:
    """Agent 图外部入口：传入上下文和意图，返回 {'reply': str, 'tool_results': list}。

    ctx 通过 LangGraph config.configurable 传递（不可序列化到 AgentState），
    routed_intent 同上用于引导 Skill 选择和置信度。"""
    config = {
        "configurable": {
            "agent_context": ctx,
            "routed_intent": routed_intent,
        }
    }
    logger.info(
        "[agent] 开始 tenant=%s conv=%s intent=%s route=%s",
        ctx.tenant_id, ctx.conversation_id,
        routed_intent.primary_intent, routed_intent.route,
    )
    result = await _agent_graph.ainvoke({}, config=config)

    reply = result.get("final_reply", "") or ""
    tool_results = result.get("tool_results", [])
    if result.get("error"):
        logger.warning(
            "[agent] 完成(mode=%s reply_len=%s tool_calls=%s error=%s)",
            result.get("execution_mode"), len(reply), result.get("tool_call_count"), result["error"],
        )
    return {"reply": reply, "tool_results": tool_results}
