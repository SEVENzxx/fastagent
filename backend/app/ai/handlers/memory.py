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

logger = logging.getLogger(__name__)


class MemoryHandler(BaseHandler):
    """记忆 Handler。

    支持 memory.* 场景：
      - memory.save
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

        if not text.strip():
            return HandlerResult(
                scenario_id=scenario,
                reply=MemoryReplyBuilder.no_text(),
                pending_directive=PendingDirective.CLEAR,
            )

        if ctx.contact_id is None:
            return HandlerResult(
                scenario_id=scenario,
                reply=MemoryReplyBuilder.no_contact(),
                pending_directive=PendingDirective.CLEAR,
            )

        result = await self._call_skill(
            "remember_info",
            tenant_id=ctx.tenant_id,
            contact_id=ctx.contact_id,
            customer_text=text,
        )

        if not result.ok:
            logger.warning(
                "【记忆保存失败】tenant_id=%s contact_id=%s error=%s",
                ctx.tenant_id, ctx.contact_id, result.error,
            )
            return HandlerResult(
                scenario_id=scenario,
                reply=MemoryReplyBuilder.error(result.error),
                pending_directive=PendingDirective.CLEAR,
            )

        saved = (result.result or {}).get("saved", [])
        if saved:
            reply = MemoryReplyBuilder.saved(saved)
        else:
            reply = MemoryReplyBuilder.nothing_saved()

        return HandlerResult(
            scenario_id=scenario,
            reply=reply,
            pending_directive=PendingDirective.CLEAR,
        )

    # ── 内部方法 ──

    async def _call_skill(
        self,
        method: str,
        **kwargs: Any,
    ) -> ToolResult:
        """调用 Skill 方法，自动注入 db session 并提交事务。

        memory.save 是写操作，成功时 commit()，失败时 rollback()。
        DB 不可用时先尝试 db=None（兼容 FakeSkill），失败则返回空 ToolResult。
        """
        if self._skill is None:
            import app.ai.skills.memory as _real_skill
            self._skill = _real_skill

        fn = getattr(self._skill, method, None)
        if fn is None:
            logger.warning("Skill 方法不存在: %s", method)
            return ToolResult(ok=False, skill_name=method, error="记忆服务暂不可用")

        try:
            from app.database import AsyncSessionLocal
        except Exception:
            try:
                return await fn(db=None, **kwargs)
            except Exception:
                logger.warning("Skill 调用失败（DB 不可用）: method=%s", method)
                return ToolResult(ok=False, skill_name=method, error="记忆服务暂不可用")

        try:
            async with AsyncSessionLocal() as db:
                result = await fn(db=db, **kwargs)
                if result.ok:
                    await db.commit()
                else:
                    await db.rollback()
                return result
        except Exception:
            logger.warning("Skill 调用失败（DB 运行时异常）: method=%s", method)
            return ToolResult(ok=False, skill_name=method, error="记忆服务暂不可用")
