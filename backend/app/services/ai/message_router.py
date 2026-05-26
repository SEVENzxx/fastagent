"""AI MessageRouter：把 RoutedIntent 分发到对应处理器。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.services.ai.handlers.agent import handle_agent
from app.services.ai.handlers.general_reply import handle_general_reply
from app.services.ai.handlers.human import handle_human
from app.services.ai.handlers.silent import handle_silent
from app.services.ai.intent.types import RoutedIntent


@dataclass(frozen=True, slots=True)
class MessageRouterResult:
    """轻量调度结果，后续可替换为真实 handler 输出。"""

    route: str
    skill: str | None
    message: str


class MessageRouter:
    """Phase 8 调度入口。"""

    async def dispatch(self, routed: RoutedIntent) -> MessageRouterResult:
        """根据 route 返回非流式处理结果。"""
        if routed.route == "HUMAN":
            return MessageRouterResult(routed.route, routed.skill, await handle_human(routed))
        if routed.route == "SILENT":
            return MessageRouterResult(routed.route, routed.skill, await handle_silent(routed))
        if routed.route == "AGENT":
            return MessageRouterResult(routed.route, routed.skill, await handle_agent(routed))
        # GENERAL_REPLY 走流式收集结果
        chunks: list[str] = []
        async for chunk in handle_general_reply(routed):
            chunks.append(chunk)
        return MessageRouterResult(routed.route, routed.skill, "".join(chunks))

    async def dispatch_stream(self, routed: RoutedIntent) -> AsyncIterator[str]:
        """根据 route 流式返回回复片段。

        GENERAL_REPLY 走 LLM 流式生成，逐 chunk 输出；其余 route 固定话术一次输出。
        上层通过 ``async for chunk in router.dispatch_stream(routed):`` 消费，
        每个 chunk 通过 WebSocket 发送 ``message.chunk`` 事件，流结束后发送 ``message.created``。
        """
        if routed.route == "GENERAL_REPLY":
            async for chunk in handle_general_reply(routed):
                yield chunk
        else:
            result = await self.dispatch(routed)
            yield result.message
