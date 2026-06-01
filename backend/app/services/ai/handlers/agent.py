"""AGENT 路由处理器 — LangGraph Agent。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from app.services.ai.agent.types import AgentContext
from app.services.ai.handlers.registry import register_handler
from app.services.ai.intent.types import RoutedIntent

logger = logging.getLogger(__name__)


async def handle_agent(
    routed: RoutedIntent,
    *,
    agent_context: AgentContext | None = None,
) -> dict:
    """通过 LangGraph Agent 处理 AGENT 路由，返回 {"reply": str, "tool_results": list}。"""
    logger.info(
        "AGENT handler 调用 LangGraph Agent：tenant_id=%s conversation_id=%s intent=%s skill=%s confidence=%.4f",
        agent_context.tenant_id,
        agent_context.conversation_id,
        routed.primary_intent,
        routed.skill,
        routed.confidence,
    )

    from app.services.ai.agent import run_agent

    result = await run_agent(agent_context, routed)
    return result


@register_handler("AGENT")
class AgentHandler:
    """AGENT 路由处理器。"""

    route = "AGENT"
    reply_sender_type = "AI"
    clear_pending_state = False
    transfer_to_human = False
    send_ai_greeting = True
    show_typing = True
    requires_agent_context = True

    def __init__(self):
        self.last_tool_results: list[dict] = []

    async def handle(
        self,
        routed: RoutedIntent,
        *,
        agent_context: AgentContext | None = None,
    ) -> str:
        result = await handle_agent(routed, agent_context=agent_context)
        self.last_tool_results = result.get("tool_results", [])
        return result["reply"]

    async def stream(
        self,
        routed: RoutedIntent,
        *,
        agent_context: AgentContext | None = None,
    ) -> AsyncIterator[str]:
        yield await self.handle(routed, agent_context=agent_context)
