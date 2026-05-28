from collections.abc import AsyncIterator

import pytest

from app.services.ai.handlers.registry import get_handler, registered_routes
from app.services.ai.intent.types import RoutedIntent
from app.services.ai.message_router import MessageRouter


def _routed(route: str, *, skill: str | None = None) -> RoutedIntent:
    return RoutedIntent(
        primary_intent="test_intent",
        confidence=0.9,
        route=route,
        skill=skill,
        hits=[],
        is_multi_intent=False,
        need_clarification=False,
        reason="test",
    )


def test_builtin_route_handlers_are_registered():
    """内置 route handler 应通过装饰器自动注册。"""

    assert set(registered_routes()) >= {"AGENT", "GENERAL_REPLY", "HUMAN", "SILENT"}
    assert get_handler("HUMAN").route == "HUMAN"
    assert get_handler("SILENT").route == "SILENT"
    assert get_handler("AGENT").route == "AGENT"
    assert get_handler("GENERAL_REPLY").route == "GENERAL_REPLY"


def test_message_router_resolve_returns_handler_policy():
    """MessageRouter resolve 应直接返回 handler 策略。"""

    human_handler = MessageRouter().resolve(_routed("HUMAN"))
    agent_handler = MessageRouter().resolve(_routed("AGENT", skill="search_products"))
    silent_handler = MessageRouter().resolve(_routed("SILENT"))

    assert human_handler.reply_sender_type == "SYSTEM"
    assert human_handler.transfer_to_human is True
    assert human_handler.clear_pending_state is True
    assert agent_handler.reply_sender_type == "AI"
    assert agent_handler.requires_agent_context is True
    assert agent_handler.show_typing is True
    assert silent_handler.reply_sender_type is None


@pytest.mark.asyncio
async def test_message_router_dispatch_uses_registered_handler():
    """MessageRouter 应通过注册表调用处理器，而不是 route if-else。"""

    result = await MessageRouter().dispatch(_routed("HUMAN"))

    assert result.route == "HUMAN"
    assert result.skill is None
    assert result.message == "您已接入人工客服，请稍候，客服人员将尽快为您服务。"



def test_handler_protocol_accepts_stream_method():
    """注册表返回的 handler 应提供统一 stream 方法。"""

    stream = get_handler("HUMAN").stream(_routed("HUMAN"))

    assert isinstance(stream, AsyncIterator)
