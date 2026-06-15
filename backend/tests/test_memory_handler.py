"""MemoryHandler 单元测试。

覆盖 memory.save 场景：
  1. 正常保存偏好 → 回复成功消息
  2. 未识别偏好 → 回复"没识别到"
  3. 空文本 → 提示输入
  4. 无 contact_id → 提示确认身份
  5. Skill 异常 → 回复错误消息
  6. 边界：text 来自 decision.entities / ctx.last_user_message
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.context.pending_state import PendingDirective
from app.ai.handlers.memory import MemoryHandler
from app.ai.recognition.types import ScenarioDecision
from app.ai.reply_builders.memory import MemoryReplyBuilder
from app.ai.context.session_context import SessionContext
from app.ai.handlers.base import ToolResult


# ══════════════════════════════════════════════
# Fake MemorySkill
# ══════════════════════════════════════════════


class FakeMemorySkill:
    """内存 MemorySkill，不依赖 LLM 或数据库。"""

    saved_items: list[dict[str, Any]] = []
    fail_next: bool = False
    fail_message: str | None = None

    @classmethod
    def reset(cls) -> None:
        cls.saved_items = []
        cls.fail_next = False
        cls.fail_message = None

    @classmethod
    def add_saved_item(cls, key: str, value: str) -> None:
        cls.saved_items.append({"key": key, "value": value})

    @classmethod
    async def remember_info(
        cls,
        *,
        tenant_id: int,
        contact_id: int | None = None,
        db: Any = None,
        **kwargs: Any,
    ) -> ToolResult:
        if cls.fail_next:
            cls.fail_next = False
            return ToolResult(
                ok=False,
                skill_name="remember_info",
                error=cls.fail_message,
            )

        _ = tenant_id, contact_id, db
        customer_text = str(kwargs.get("customer_text") or "").strip()
        if not customer_text:
            return ToolResult(
                ok=False, skill_name="remember_info", error="缺少客户消息文本",
            )

        if not cls.saved_items:
            return ToolResult(
                ok=True, skill_name="remember_info",
                result={"saved": [], "message": "暂未识别到特定偏好"},
            )

        saved = [f"{item['key']}={item['value']}" for item in cls.saved_items]
        return ToolResult(
            ok=True, skill_name="remember_info",
            result={"saved": saved, "message": f"已记住: {', '.join(saved)}"},
        )


# ══════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════


def make_decision(
    scenario_id: str = "memory.save",
    raw_text: str = "",
) -> ScenarioDecision:
    return ScenarioDecision(
        scenario_id=scenario_id,
        confidence=0.95,
        entities={"raw_text": raw_text} if raw_text else {},
    )


def make_context(
    tenant_id: int = 1,
    conversation_id: int = 1,
    contact_id: int | None = 1,
    last_user_message: str = "",
) -> SessionContext:
    return SessionContext(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        contact_id=contact_id,
        last_user_message=last_user_message,
    )


# ══════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════


class TestMemorySave:
    """memory.save 正常保存。"""

    @pytest.mark.asyncio
    async def test_save_preference(self) -> None:
        """保存偏好 → 回复成功消息。"""
        FakeMemorySkill.reset()
        FakeMemorySkill.add_saved_item("favorite_flavor", "草莓")
        FakeMemorySkill.add_saved_item("shipping_preference", "下午配送")

        handler = MemoryHandler(skill=FakeMemorySkill)
        result = await handler.execute(
            make_decision(raw_text="我喜欢草莓味，下午送货最好"),
            make_context(),
        )

        assert result.scenario_id == "memory.save"
        assert result.pending_directive == PendingDirective.CLEAR
        assert "草莓" in result.reply
        assert "下午配送" in result.reply
        assert "已帮您记住" in result.reply

    @pytest.mark.asyncio
    async def test_nothing_to_save(self) -> None:
        """无识别偏好 → nothing_saved 回复。"""
        FakeMemorySkill.reset()

        handler = MemoryHandler(skill=FakeMemorySkill)
        result = await handler.execute(
            make_decision(raw_text="今天天气不错"),
            make_context(),
        )

        assert result.reply == MemoryReplyBuilder.nothing_saved()

    @pytest.mark.asyncio
    async def test_empty_text(self) -> None:
        """空文本 → 提示输入。"""
        FakeMemorySkill.reset()

        handler = MemoryHandler(skill=FakeMemorySkill)
        result = await handler.execute(
            make_decision(),
            make_context(last_user_message=""),
        )

        assert result.reply == MemoryReplyBuilder.no_text()

    @pytest.mark.asyncio
    async def test_text_from_context(self) -> None:
        """文本从 ctx.last_user_message 获取。"""
        FakeMemorySkill.reset()
        FakeMemorySkill.add_saved_item("color", "蓝色")

        handler = MemoryHandler(skill=FakeMemorySkill)
        result = await handler.execute(
            make_decision(),
            make_context(last_user_message="我喜欢蓝色"),
        )

        assert "蓝色" in result.reply
        assert "已帮您记住" in result.reply

    @pytest.mark.asyncio
    async def test_no_contact_id(self) -> None:
        """无 contact_id → 提示确认身份。"""
        FakeMemorySkill.reset()

        handler = MemoryHandler(skill=FakeMemorySkill)
        result = await handler.execute(
            make_decision(raw_text="记住我的偏好"),
            make_context(contact_id=None),
        )

        assert result.reply == MemoryReplyBuilder.no_contact()

    @pytest.mark.asyncio
    async def test_skill_error(self) -> None:
        """Skill 异常 → 回复错误消息。"""
        FakeMemorySkill.reset()
        FakeMemorySkill.fail_next = True
        FakeMemorySkill.fail_message = "LLM 服务异常"

        handler = MemoryHandler(skill=FakeMemorySkill)
        result = await handler.execute(
            make_decision(raw_text="记住我的偏好"),
            make_context(),
        )

        assert "LLM 服务异常" in result.reply or "保存偏好" in result.reply

    @pytest.mark.asyncio
    async def test_skill_error_default_message(self) -> None:
        """Skill 异常无错误消息 → 默认错误回复。"""
        FakeMemorySkill.reset()
        FakeMemorySkill.fail_next = True
        FakeMemorySkill.fail_message = None

        handler = MemoryHandler(skill=FakeMemorySkill)
        result = await handler.execute(
            make_decision(raw_text="记住我的偏好"),
            make_context(),
        )

        assert result.reply == MemoryReplyBuilder.error()

    @pytest.mark.asyncio
    async def test_commit_on_success(self) -> None:
        """Skill 成功时 _call_skill 提交事务。"""
        FakeMemorySkill.reset()
        FakeMemorySkill.add_saved_item("color", "蓝色")

        mock_db = AsyncMock()
        mock_db.__aenter__.return_value = mock_db

        mock_sessionmaker = MagicMock(return_value=mock_db)
        mock_module = MagicMock()
        mock_module.AsyncSessionLocal = mock_sessionmaker

        old = sys.modules.pop("app.integrations.database", None)
        sys.modules["app.integrations.database"] = mock_module
        try:
            handler = MemoryHandler(skill=FakeMemorySkill)
            result = await handler.execute(
                make_decision(raw_text="我喜欢蓝色"),
                make_context(),
            )
        finally:
            if old is not None:
                sys.modules["app.integrations.database"] = old
            else:
                del sys.modules["app.integrations.database"]

        assert "已帮您记住" in result.reply
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rollback_on_failure(self) -> None:
        """Skill 失败时 _call_skill 回滚事务。"""
        FakeMemorySkill.reset()
        FakeMemorySkill.fail_next = True
        FakeMemorySkill.fail_message = "DB 错误"

        mock_db = AsyncMock()
        mock_db.__aenter__.return_value = mock_db

        mock_sessionmaker = MagicMock(return_value=mock_db)
        mock_module = MagicMock()
        mock_module.AsyncSessionLocal = mock_sessionmaker

        old = sys.modules.pop("app.integrations.database", None)
        sys.modules["app.integrations.database"] = mock_module
        try:
            handler = MemoryHandler(skill=FakeMemorySkill)
            result = await handler.execute(
                make_decision(raw_text="记住我的偏好"),
                make_context(),
            )
        finally:
            if old is not None:
                sys.modules["app.integrations.database"] = old
            else:
                del sys.modules["app.integrations.database"]

        assert "DB 错误" in result.reply or "保存偏好" in result.reply
        mock_db.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pending_directive_always_clear(self) -> None:
        """所有路径 PendingDirective 必须为 CLEAR。"""
        FakeMemorySkill.reset()

        handler = MemoryHandler(skill=FakeMemorySkill)

        # 成功
        r1 = await handler.execute(make_decision(raw_text="测试"), make_context())
        assert r1.pending_directive == PendingDirective.CLEAR

        # 空文本
        r2 = await handler.execute(make_decision(), make_context(last_user_message=""))
        assert r2.pending_directive == PendingDirective.CLEAR

        # 无 contact
        r3 = await handler.execute(
            make_decision(raw_text="测试"), make_context(contact_id=None),
        )
        assert r3.pending_directive == PendingDirective.CLEAR
