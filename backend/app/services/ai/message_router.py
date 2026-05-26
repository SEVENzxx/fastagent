"""AI MessageRouter：把 RoutedIntent 分发到对应处理器。"""

from __future__ import annotations

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
        """根据 route 返回占位处理结果。"""
        if routed.route == "HUMAN":
            return MessageRouterResult(routed.route, routed.skill, await handle_human(routed))
        if routed.route == "SILENT":
            return MessageRouterResult(routed.route, routed.skill, await handle_silent(routed))
        if routed.route == "AGENT":
            return MessageRouterResult(routed.route, routed.skill, await handle_agent(routed))
        return MessageRouterResult(routed.route, routed.skill, await handle_general_reply(routed))
