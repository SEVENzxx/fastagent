"""TemplateHandler — 模板回复 Handler。

处理以下 scenario：
  - template.greeting / template.confirmation / template.farewell
  - template.silent / template.fallback

回复文案全部集中在 TemplateReplyBuilder，Handler 只做路由。
"""

from __future__ import annotations

from app.ai.context.pending_state import PendingDirective
from app.ai.handlers.base import BaseHandler, HandlerResult
from app.ai.recognition.types import ScenarioDecision
from app.ai.reply_builders.template import TemplateReplyBuilder


class TemplateHandler(BaseHandler):
    """模板回复 Handler。

    支持 template.* 场景：
      - template.greeting / template.confirmation / template.farewell
      - template.silent / template.fallback
    不实现 resume()，单轮回复无需 Pending 恢复。
    """

    async def execute(
        self,
        decision: ScenarioDecision,
        context: object,
    ) -> HandlerResult:
        """返回固定模板回复。"""
        reply = TemplateReplyBuilder.for_scenario(decision.scenario_id)
        return HandlerResult(
            scenario_id=decision.scenario_id,
            reply=reply,
            pending_directive=PendingDirective.CLEAR,
        )
