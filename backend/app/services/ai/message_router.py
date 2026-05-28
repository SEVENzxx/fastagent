"""AI MessageRouter：把 RoutedIntent 分发到对应处理器。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.services.ai.agent.types import AgentContext
from app.services.ai.handlers.registry import RouteHandler, get_handler
from app.services.ai.intent.types import RoutedIntent

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MessageRouterResult:
    """轻量调度结果。"""

    route: str
    skill: str | None
    message: str


ChunkCallback = Callable[[str], Awaitable[None]]


class MessageRouter:

    def resolve(self, routed: RoutedIntent) -> RouteHandler:
        """根据 routed intent 获取对应处理器。"""

        handler = get_handler(routed.route)
        logger.info(
            "消息路由器解析处理器：route=%s handler=%s sender_type=%s transfer=%s typing=%s",
            routed.route,
            handler.__class__.__name__,
            handler.reply_sender_type,
            handler.transfer_to_human,
            handler.show_typing,
        )
        return handler

    async def dispatch(
        self,
        routed: RoutedIntent,
        *,
        agent_context: AgentContext | None = None,
    ) -> MessageRouterResult:
        """根据 route 返回非流式处理结果。"""
        logger.info(
            "消息路由器开始调度：route=%s skill=%s intent=%s confidence=%.4f",
            routed.route,
            routed.skill,
            routed.primary_intent,
            routed.confidence,
        )
        handler = self.resolve(routed)
        message = await self.render(routed, handler=handler, agent_context=agent_context)
        return MessageRouterResult(routed.route, routed.skill, message)

    async def render(
        self,
        routed: RoutedIntent,
        *,
        handler: RouteHandler | None = None,
        agent_context: AgentContext | None = None,
        on_chunk: ChunkCallback | None = None,
    ) -> str:
        """执行 route handler 并返回完整文本。

        如果传入 ``on_chunk``，每个流式片段会同步回调给上层用于 WebSocket 推送。
        """

        selected_handler = handler or self.resolve(routed)
        chunks: list[str] = []
        async for chunk in selected_handler.stream(routed, agent_context=agent_context):
            chunks.append(chunk)
            if on_chunk is not None:
                await on_chunk(chunk)
        return "".join(chunks)


