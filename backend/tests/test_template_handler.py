"""TemplateHandler 单元测试。

覆盖所有 template.* 子场景：
  1. template.greeting → 问候
  2. template.confirmation → 确认
  3. template.farewell → 告别
  4. template.silent → 静默
  5. template.fallback → 兜底
  6. 未注册 scenario_id → 走 fallback
"""

from __future__ import annotations

import pytest

from app.ai.context.pending_state import PendingDirective
from app.ai.handlers.template import TemplateHandler
from app.ai.recognition.types import ScenarioDecision
from app.ai.reply_builders.template import TemplateReplyBuilder
from app.ai.context.session_context import SessionContext


# ══════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════


def make_decision(scenario_id: str) -> ScenarioDecision:
    return ScenarioDecision(
        scenario_id=scenario_id,
        confidence=1.0,
        entities={},
    )


def make_context() -> SessionContext:
    return SessionContext(tenant_id=1, conversation_id=1)


# ══════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════


class TestTemplateGreeting:
    """template.greeting → 问候。"""

    @pytest.mark.asyncio
    async def test_greeting(self) -> None:
        handler = TemplateHandler()
        result = await handler.execute(make_decision("template.greeting"), make_context())

        assert result.scenario_id == "template.greeting"
        assert result.reply == TemplateReplyBuilder.for_scenario("template.greeting")
        assert result.pending_directive == PendingDirective.CLEAR


class TestTemplateConfirmation:
    """template.confirmation → 确认。"""

    @pytest.mark.asyncio
    async def test_confirmation(self) -> None:
        handler = TemplateHandler()
        result = await handler.execute(
            make_decision("template.confirmation"), make_context(),
        )

        assert result.scenario_id == "template.confirmation"
        assert result.reply == TemplateReplyBuilder.for_scenario("template.confirmation")
        assert result.pending_directive == PendingDirective.CLEAR


class TestTemplateFarewell:
    """template.farewell → 告别。"""

    @pytest.mark.asyncio
    async def test_farewell(self) -> None:
        handler = TemplateHandler()
        result = await handler.execute(
            make_decision("template.farewell"), make_context(),
        )

        assert result.scenario_id == "template.farewell"
        assert result.reply == TemplateReplyBuilder.for_scenario("template.farewell")
        assert result.pending_directive == PendingDirective.CLEAR


class TestTemplateSilent:
    """template.silent → 静默。"""

    @pytest.mark.asyncio
    async def test_silent(self) -> None:
        handler = TemplateHandler()
        result = await handler.execute(
            make_decision("template.silent"), make_context(),
        )

        assert result.scenario_id == "template.silent"
        assert result.reply == "..."
        assert result.pending_directive == PendingDirective.CLEAR


class TestTemplateFallback:
    """template.fallback → 兜底。"""

    @pytest.mark.asyncio
    async def test_fallback(self) -> None:
        handler = TemplateHandler()
        result = await handler.execute(
            make_decision("template.fallback"), make_context(),
        )

        assert result.scenario_id == "template.fallback"
        assert result.reply == TemplateReplyBuilder.for_scenario("template.fallback")
        assert result.pending_directive == PendingDirective.CLEAR


class TestTemplateUnknownScenario:
    """未注册 scenario_id → fallback 回复。"""

    @pytest.mark.asyncio
    async def test_unknown_scenario_falls_back(self) -> None:
        handler = TemplateHandler()
        result = await handler.execute(
            make_decision("template.unknown"), make_context(),
        )

        assert result.reply == TemplateReplyBuilder.for_scenario("template.fallback")
        assert result.pending_directive == PendingDirective.CLEAR


class TestTemplateReplyBuilder:
    """TemplateReplyBuilder 构造验证。"""

    def test_all_scenarios_have_replies(self) -> None:
        """所有模板场景都有对应回复。"""
        scenarios = [
            "template.greeting",
            "template.confirmation",
            "template.farewell",
            "template.silent",
            "template.fallback",
        ]
        for sid in scenarios:
            reply = TemplateReplyBuilder.for_scenario(sid)
            assert reply, f"场景 {sid} 缺少模板回复"
            assert len(reply) > 0

    def test_unknown_scenario_default(self) -> None:
        """未知场景返回 fallback。"""
        assert TemplateReplyBuilder.for_scenario("template.unknown") == \
               TemplateReplyBuilder.for_scenario("template.fallback")
