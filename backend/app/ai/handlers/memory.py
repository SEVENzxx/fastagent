"""MemoryHandler — 记忆场景 Handler。

支持以下 scenario：
  - memory.save

Handler 编排 MemorySkill → MemoryReplyBuilder。
长期记忆直接落 DB（sales_memories 表），不写 SessionContext。
"""

from __future__ import annotations

import logging
from typing import Any

from app.ai.context.pending_state import PendingDirective
from app.ai.handlers.base import BaseHandler, HandlerResult
from app.ai.recognition.types import ScenarioDecision
from app.ai.reply_builders.memory import MemoryReplyBuilder
from app.ai.context.session_context import SessionContext
from app.ai.handlers.base import ToolResult
from app.ai.skills.gateway import SkillError, call_skill, call_skill_tx

logger = logging.getLogger(__name__)


class MemoryHandler(BaseHandler):
    """记忆 Handler。

    支持 memory.* 场景：
      - memory.save
      - memory.recall
    不实现 resume()，单轮操作无需 Pending 恢复。
    """

    def __init__(self, skill: object = None) -> None:
        self._skill = skill

    async def execute(
        self,
        decision: ScenarioDecision,
        context: object,
    ) -> HandlerResult:
        """处理记忆场景。"""
        ctx: SessionContext = context  # type: ignore[assignment]
        scenario = decision.scenario_id
        text = decision.entities.get("raw_text", "")
        if not text:
            text = getattr(ctx, "last_user_message", "") or ""

        self._init_trace_context(scenario)

        if not text.strip():
            result = HandlerResult(
                scenario_id=scenario,
                reply=MemoryReplyBuilder.no_text(),
                pending_directive=PendingDirective.CLEAR,
            )
        elif ctx.contact_id is None:
            result = HandlerResult(
                scenario_id=scenario,
                reply=MemoryReplyBuilder.no_contact(),
                pending_directive=PendingDirective.CLEAR,
            )
        elif scenario == "memory.recall":
            skill_result = await self._call_skill(
                "recall_info",
                tenant_id=ctx.tenant_id,
                contact_id=ctx.contact_id,
            )
            if skill_result.ok:
                items = (skill_result.result or {}).get("items", [])
                reply = MemoryReplyBuilder.recall(items)
            else:
                reply = MemoryReplyBuilder.error(skill_result.error)
            result = HandlerResult(
                scenario_id=scenario,
                reply=reply,
                pending_directive=PendingDirective.CLEAR,
            )
        else:
            skill_result = await self._call_skill(
                "remember_info",
                tenant_id=ctx.tenant_id,
                contact_id=ctx.contact_id,
                customer_text=text,
            )
            if not skill_result.ok:
                logger.warning(
                    "【记忆保存失败】tenant_id=%s contact_id=%s error=%s",
                    ctx.tenant_id, ctx.contact_id, skill_result.error,
                )
                result = HandlerResult(
                    scenario_id=scenario,
                    reply=MemoryReplyBuilder.error(skill_result.error),
                    pending_directive=PendingDirective.CLEAR,
                )
            else:
                saved = (skill_result.result or {}).get("saved", [])
                reply = MemoryReplyBuilder.saved(saved) if saved else MemoryReplyBuilder.nothing_saved()
                result = HandlerResult(
                    scenario_id=scenario,
                    reply=reply,
                    pending_directive=PendingDirective.CLEAR,
                )

        self._merge_trace_context(result)
        return result

    # ── 内部方法 ──

    async def _call_skill(
        self,
        method: str,
        **kwargs: Any,
    ) -> ToolResult:
        """调用 Skill 方法（通过 SkillGateway 自动记录 trace + 管理 DB session + 事务）。"""
        if self._skill is None:
            import app.ai.skills.memory as _real_skill
            self._skill = _real_skill
        try:
            return await call_skill_tx(self._skill, method, **kwargs)
        except SkillError:
            logger.warning("Skill 调用失败: method=%s", method)
            return ToolResult(ok=False, skill_name=method, error="记忆服务暂不可用")
