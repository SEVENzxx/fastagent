"""SILENT 路由处理器。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from app.services.ai.intent.types import ROUTE_SILENT, RoutedIntent
from app.services.ai.handlers.registry import register_handler

if TYPE_CHECKING:
    from app.services.ai.agent.types import AgentContext


async def handle_silent(_routed: RoutedIntent) -> str:
    """静默处理：不回复内容。"""
    return ""


@register_handler(ROUTE_SILENT)
class SilentHandler:
    """SILENT 路由处理器。"""

    route = ROUTE_SILENT
    reply_sender_type = None
    clear_pending_state = False
    transfer_to_human = False
    send_ai_greeting = False
    show_typing = False
    requires_agent_context = False

    async def handle(
        self,
        routed: RoutedIntent,
        *,
        agent_context: AgentContext | None = None,
    ) -> str:
        return await handle_silent(routed)

    async def stream(
        self,
        routed: RoutedIntent,
        *,
        agent_context: AgentContext | None = None,
    ) -> AsyncIterator[str]:
        result = await self.handle(routed)
        if result:
            yield result
