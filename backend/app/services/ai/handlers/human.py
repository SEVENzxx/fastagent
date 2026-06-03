"""HUMAN 路由处理器。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from app.services.ai.handlers.registry import register_handler
from app.services.ai.intent.types import ROUTE_HUMAN, RoutedIntent

if TYPE_CHECKING:
    from app.services.ai.agent.types import AgentContext


@register_handler(ROUTE_HUMAN)
class HumanHandler:
    """HUMAN 路由处理器。"""

    route = ROUTE_HUMAN
    reply_sender_type = "SYSTEM"
    clear_pending_state = True
    transfer_to_human = True
    send_ai_greeting = False
    show_typing = False
    requires_agent_context = False
    tool_results: list[dict] = []

    async def handle(
        self,
        routed: RoutedIntent,
        *,
        agent_context: AgentContext | None = None,
    ) -> str:
        return "您已接入人工客服，请稍候，客服人员将尽快为您服务。"

    async def stream(
        self,
        routed: RoutedIntent,
        *,
        agent_context: AgentContext | None = None,
    ) -> AsyncIterator[str]:
        yield await self.handle(routed)
