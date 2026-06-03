"""AI MessageRouter：把 RoutedIntent 分发到对应处理器。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.services.ai.agent.types import AgentContext
from app.services.ai.handlers.registry import RouteHandler, get_handler
from app.services.ai.intent.types import RoutedIntent

logger = logging.getLogger(__name__)

ChunkCallback = Callable[[str], Awaitable[None]]


@dataclass
class RenderResult:
    """render() 返回值：文本回复 + 结构化数据（订单卡片等）。"""

    text: str
    tool_results: list[dict]


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

    async def render(
        self,
        routed: RoutedIntent,
        *,
        handler: RouteHandler | None = None,
        agent_context: AgentContext | None = None,
        on_chunk: ChunkCallback | None = None,
    ) -> RenderResult:
        """执行 route handler 并返回文本 + 结构化数据。

        如果传入 ``on_chunk``，每个流式片段会同步回调给上层用于 WebSocket 推送。
        结构化数据从 handler.tool_results 读取（Agent 执行后填充）。
        """

        selected_handler = handler or self.resolve(routed)
        chunks: list[str] = []
        async for chunk in selected_handler.stream(routed, agent_context=agent_context):
            chunks.append(chunk)
            if on_chunk is not None:
                await on_chunk(chunk)
        return RenderResult(
            text="".join(chunks),
            tool_results=getattr(selected_handler, "tool_results", []),
        )


