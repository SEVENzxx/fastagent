"""HumanHandler — 转人工 Handler。

处理 human.transfer 场景，统一返回转人工话术并清理 Pending。
通过 context_update 传递 requires_human_handoff 信号，
processor 消费该信号后执行 DB 状态更新和 WebSocket 广播。
"""

from __future__ import annotations

import logging
from typing import Any

from app.ai.context.pending_state import PendingDirective
from app.ai.handlers.base import BaseHandler, HandlerResult
from app.ai.recognition.types import ScenarioDecision
from app.ai.reply_builders.human import HumanReplyBuilder
from app.ai.context.session_context import SessionContext

logger = logging.getLogger(__name__)


class HumanHandler(BaseHandler):
    """转人工 Handler。

    处理 human.transfer 场景。
    返回 context_update 携带 requires_human_handoff 信号，
    processor 检测后执行转人工业务逻辑（会话状态变更、坐席分配、WebSocket 广播）。
    PendingDirective.CLEAR 确保清空当前 Pending 状态。
    不实现 resume()，转人工后无继续恢复语义。
    """

    async def execute(
        self,
        decision: ScenarioDecision,
        context: object,
    ) -> HandlerResult:
        """执行转人工。"""
        ctx: SessionContext = context  # type: ignore[assignment]

        reason = decision.entities.get("reason", "用户要求人工客服")
        text = decision.entities.get("raw_text", "")
        if not text:
            text = getattr(ctx, "last_user_message", "") or ""

        logger.info(
            "【转人工】tenant_id=%s conversation_id=%s reason=%s",
            ctx.tenant_id, ctx.conversation_id, reason,
        )

        context_update: dict[str, Any] = {
            "requires_human_handoff": True,
            "pending_human_approval": {
                "reason": reason,
                "trigger_text": text[:100],
            },
        }

        return HandlerResult(
            scenario_id=decision.scenario_id,
            reply=HumanReplyBuilder.transfer(),
            pending_directive=PendingDirective.CLEAR,
            context_update=context_update,
        )
