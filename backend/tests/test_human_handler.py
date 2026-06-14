"""HumanHandler 单元测试。

覆盖 human.transfer 场景：
  1. 转人工 → "正在为您转接"
  2. PendingDirective 必须为 CLEAR
  3. HumanReplyBuilder 格式验证
"""

from __future__ import annotations

import pytest

from app.ai.context.pending_state import PendingDirective
from app.ai.handlers.human import HumanHandler
from app.ai.recognition.types import ScenarioDecision
from app.ai.reply_builders.human import HumanReplyBuilder
from app.ai.context.session_context import SessionContext


# ══════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════


def make_decision(
    scenario_id: str = "human.transfer",
    reason: str = "用户要求人工客服",
) -> ScenarioDecision:
    return ScenarioDecision(
        scenario_id=scenario_id,
        confidence=1.0,
        entities={"reason": reason},
    )


def make_context() -> SessionContext:
    return SessionContext(tenant_id=1, conversation_id=1)


# ══════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════


class TestHumanTransfer:
    """human.transfer 转人工。"""

    @pytest.mark.asyncio
    async def test_transfer(self) -> None:
        handler = HumanHandler()
        result = await handler.execute(make_decision(), make_context())

        assert result.scenario_id == "human.transfer"
        assert result.reply == HumanReplyBuilder.transfer()
        assert "转接人工客服" in result.reply

    @pytest.mark.asyncio
    async def test_pending_directive_is_clear(self) -> None:
        """转人工后必须 CLEAR。"""
        handler = HumanHandler()
        result = await handler.execute(make_decision(), make_context())

        assert result.pending_directive == PendingDirective.CLEAR

    @pytest.mark.asyncio
    async def test_no_pending_state(self) -> None:
        """转人工后不保留 PendingState。"""
        handler = HumanHandler()
        result = await handler.execute(make_decision(), make_context())

        assert result.pending_state is None

    @pytest.mark.asyncio
    async def test_context_update_has_handoff_signals(self) -> None:
        """转人工后 context_update 携带 handoff 信号。"""
        handler = HumanHandler()
        result = await handler.execute(make_decision(), make_context())

        assert result.context_update.get("requires_human_handoff") is True
        assert "pending_human_approval" in result.context_update
        approval = result.context_update["pending_human_approval"]
        assert isinstance(approval, dict)
        assert "reason" in approval
        assert "trigger_text" in approval


class TestHumanReplyBuilder:
    """HumanReplyBuilder 格式验证。"""

    def test_transfer_message(self) -> None:
        reply = HumanReplyBuilder.transfer()
        assert "转接人工客服" in reply
        assert len(reply) > 5
