"""GENERAL_REPLY 路由处理器 — 委托给 GeneralQAFlow。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from app.ai.classifier.types import ROUTE_GENERAL_REPLY, RoutedIntent
from app.ai.flows.general_qa_flow import GeneralQAFlow
from app.ai.router.handlers.registry import register_handler

if TYPE_CHECKING:
    from app.ai.agent.types import AgentContext


@register_handler(ROUTE_GENERAL_REPLY)
class GeneralReplyHandler:
    """GENERAL_REPLY 路由处理器 — 委托给 GeneralQAFlow。

    这里只是工程入口适配层：负责把 RouteHandler 协议的方法调用
    委托给通用问答 Flow，让 Flow 专注业务逻辑。
    """

    route = GeneralQAFlow.route
    reply_sender_type = GeneralQAFlow.reply_sender_type
    clear_pending_state = GeneralQAFlow.clear_pending_state
    transfer_to_human = GeneralQAFlow.transfer_to_human
    send_ai_greeting = GeneralQAFlow.send_ai_greeting
    show_typing = GeneralQAFlow.show_typing
    requires_agent_context = GeneralQAFlow.requires_agent_context
    tool_results: list[dict] = []

    async def handle(
        self,
        routed: RoutedIntent,
        *,
        agent_context: AgentContext | None = None,
    ) -> str:
        flow = GeneralQAFlow()
        result = await flow.handle(routed, agent_context=agent_context)
        self.tool_results = flow.tool_results
        return result

    async def stream(
        self,
        routed: RoutedIntent,
        *,
        agent_context: AgentContext | None = None,
    ) -> AsyncIterator[str]:
        flow = GeneralQAFlow()
        async for chunk in flow.stream(routed, agent_context=agent_context):
            yield chunk
        self.tool_results = flow.tool_results
