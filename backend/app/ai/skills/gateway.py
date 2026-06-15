"""SkillGateway — 技能调用网关。

模块级函数（同 LLMGateway），自动记录 ResourceTrace 并管理 DB session。

用法:
    from app.ai.skills.gateway import call_skill, call_skill_tx

    # 只读 Skill
    result = await call_skill(skill_module, "search_products", tenant_id=1)

    # 写 Skill（自动 commit/rollback）
    result = await call_skill_tx(skill_module, "remember_info", tenant_id=1, ...)
"""

from __future__ import annotations

import logging
from typing import Any

from app.ai.trace import add_skill_call, get_trace

logger = logging.getLogger(__name__)

SKILL_ERROR = "技能调用异常"


class SkillError(Exception):
    """技能调用异常，由 handler catch 后做领域降级。"""

    def __init__(self, method: str, message: str = SKILL_ERROR) -> None:
        self.method = method
        super().__init__(message)


# ── 内部辅助 ──


def _record_trace(method: str) -> None:
    """将 skill 调用记录到 contextvar trace。"""
    td = get_trace()
    if td is not None:
        add_skill_call(td, method)


async def _create_session() -> Any | None:
    """创建 DB session，失败返回 None。"""
    try:
        from app.integrations.database import AsyncSessionLocal

        return AsyncSessionLocal()
    except Exception:
        return None


def _resolve_method(skill_obj: Any, method: str) -> Any:
    """解析 skill 方法，不存在则抛 SkillError。"""
    fn = getattr(skill_obj, method, None)
    if fn is None:
        raise SkillError(method, f"Skill 方法不存在: {method}")
    return fn


# ── 公开入口 ──


async def call_skill(skill_obj: Any, method: str, **kwargs: Any) -> Any:
    """只读 Skill 调用。

    Record trace → resolve method → acquire session → call → close.
    由 handler catch SkillError 做领域降级。
    """
    _record_trace(method)
    fn = _resolve_method(skill_obj, method)
    db = await _create_session()
    if db is not None:
        try:
            return await fn(db=db, **kwargs)
        finally:
            await db.close()
    return await fn(db=None, **kwargs)


async def call_skill_tx(skill_obj: Any, method: str, **kwargs: Any) -> Any:
    """写 Skill 调用（带事务）。

    同 call_skill + 基于 ToolResult.ok 的 commit/rollback。
    """
    _record_trace(method)
    fn = _resolve_method(skill_obj, method)
    db = await _create_session()
    if db is not None:
        try:
            from app.ai.handlers.base import ToolResult

            result = await fn(db=db, **kwargs)
            if isinstance(result, ToolResult) and result.ok:
                await db.commit()
            else:
                await db.rollback()
            return result
        except Exception:
            await db.rollback()
            raise SkillError(method, "技能调用事务失败")
        finally:
            await db.close()
    return await fn(db=None, **kwargs)
