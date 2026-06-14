"""Tests for entry/processor.py — AssistantService 切换阶段 10。

覆盖：
  1. entry/processor.py 不再引用 run_orchestrator
  2. template.greeting → AssistantService 生成回复并落库
  3. human.transfer → 触发 _mark_pending_human
  4. 空 reply → 不落库不推送
  5. metadata 包含 ai_route=ASSISTANT_SERVICE / scenario_id / pending_directive / resource_trace
  6. order.create → 返回 graph Pending 回复，不报系统异常
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.assistant.result import AssistantRuntimeResult
from app.ai.context.pending_state import PendingDirective
from app.ai.handlers.base import HandlerResult, ResourceTrace
from app.ai.entry.processor import (
    ProcessingContext,
    RunAssistantOrchestrator,
)


# ══════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════


@pytest.fixture
def mock_ctx() -> MagicMock:
    """创建 mock ProcessingContext。"""
    ctx = MagicMock(spec=ProcessingContext)
    ctx.db = AsyncMock()
    ctx.conversation = MagicMock()
    ctx.conversation.id = 1
    ctx.conversation.tenant_id = 100
    ctx.conversation.contact_id = 200
    ctx.conversation_list = []
    ctx.customer_message = MagicMock()
    ctx.customer_message.id = 999
    ctx.customer_text = "你好"
    ctx.should_stop = False
    return ctx


def _make_result(
    scenario_id: str,
    reply: str,
    directive: PendingDirective = PendingDirective.CLEAR,
    context_update: dict | None = None,
    resource_trace: ResourceTrace | None = None,
) -> AssistantRuntimeResult:
    """构造 AssistantRuntimeResult 测试快捷方法。"""
    rt = resource_trace or ResourceTrace()
    handler_result = HandlerResult(
        scenario_id=scenario_id,
        reply=reply,
        pending_directive=directive,
        context_update=context_update or {},
        resource_trace=rt,
    )
    return AssistantRuntimeResult.from_handler_result(handler_result)


# ══════════════════════════════════════════════
# 测试：不再引用 run_orchestrator
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_no_run_orchestrator_import() -> None:
    """processor 不应再导入 run_orchestrator。"""
    import app.ai.entry.processor as mod

    source = mod.__file__ or ""
    with open(source, encoding="utf-8") as f:
        content = f.read()
    assert "run_orchestrator" not in content, "run_orchestrator 引用未被移除"


# ══════════════════════════════════════════════
# 测试：template.greeting 正常回复
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_template_greeting_saves_reply(mock_ctx: MagicMock) -> None:
    """template.greeting → 回复被落库广播。"""
    runtime_result = _make_result("template.greeting", "您好！有什么可以帮助您？")

    with (
        patch("app.ai.entry.processor._get_assistant_service") as mock_get,
        patch("app.ai.entry.processor._create_deliver_and_broadcast_reply_message") as mock_save,
        patch("app.ai.entry.processor.bind_usage_context"),
    ):
        mock_svc = AsyncMock()
        mock_svc.process_message = AsyncMock(return_value=runtime_result)
        mock_get.return_value = mock_svc

        step = RunAssistantOrchestrator()
        ret = await step.execute(mock_ctx)

        assert ret is True
        assert mock_ctx.should_stop is True
        mock_save.assert_awaited_once()
        args, kwargs = mock_save.call_args
        assert args[2] == "您好！有什么可以帮助您？"
        assert kwargs["sender_type"] == "AI"
        assert kwargs["metadata"]["ai_route"] == "ASSISTANT_SERVICE"
        assert kwargs["metadata"]["scenario_id"] == "template.greeting"


# ══════════════════════════════════════════════
# 测试：human.transfer 触发转人工
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_human_transfer_calls_mark_pending_human(mock_ctx: MagicMock) -> None:
    """human.transfer 的 requires_human_handoff → 调用 _mark_pending_human。"""
    context_update = {
        "requires_human_handoff": True,
        "pending_human_approval": {"reason": "用户要求人工客服", "trigger_text": "转人工"},
    }
    runtime_result = _make_result(
        "human.transfer",
        "正在为您转接人工客服，请稍候…",
        context_update=context_update,
    )

    with (
        patch("app.ai.entry.processor._get_assistant_service") as mock_get,
        patch("app.ai.entry.processor._create_deliver_and_broadcast_reply_message"),
        patch("app.ai.entry.processor._mark_pending_human") as mock_mark,
        patch("app.ai.entry.processor.bind_usage_context"),
    ):
        mock_svc = AsyncMock()
        mock_svc.process_message = AsyncMock(return_value=runtime_result)
        mock_get.return_value = mock_svc

        step = RunAssistantOrchestrator()
        await step.execute(mock_ctx)

        mock_mark.assert_awaited_once_with(
            mock_ctx.db, mock_ctx.conversation, "用户要求人工客服",
        )


@pytest.mark.asyncio
async def test_human_transfer_fallback_reason(mock_ctx: MagicMock) -> None:
    """pending_human_approval.reason 为空时使用兜底原因。"""
    context_update = {
        "requires_human_handoff": True,
        "pending_human_approval": {},
    }
    runtime_result = _make_result(
        "human.transfer",
        "正在为您转接人工客服，请稍候…",
        context_update=context_update,
    )

    with (
        patch("app.ai.entry.processor._get_assistant_service") as mock_get,
        patch("app.ai.entry.processor._create_deliver_and_broadcast_reply_message"),
        patch("app.ai.entry.processor._mark_pending_human") as mock_mark,
        patch("app.ai.entry.processor.bind_usage_context"),
    ):
        mock_svc = AsyncMock()
        mock_svc.process_message = AsyncMock(return_value=runtime_result)
        mock_get.return_value = mock_svc

        step = RunAssistantOrchestrator()
        await step.execute(mock_ctx)

        mock_mark.assert_awaited_once_with(
            mock_ctx.db, mock_ctx.conversation, "AI 判定需要人工处理",
        )


# ══════════════════════════════════════════════
# 测试：空 reply 不落库不推送
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_empty_reply_skips_save(mock_ctx: MagicMock) -> None:
    """空 reply → should_stop=True，不调 _create_deliver_and_broadcast_reply_message。"""
    runtime_result = _make_result("template.fallback", "")

    with (
        patch("app.ai.entry.processor._get_assistant_service") as mock_get,
        patch("app.ai.entry.processor._create_deliver_and_broadcast_reply_message") as mock_save,
        patch("app.ai.entry.processor.bind_usage_context"),
    ):
        mock_svc = AsyncMock()
        mock_svc.process_message = AsyncMock(return_value=runtime_result)
        mock_get.return_value = mock_svc

        step = RunAssistantOrchestrator()
        ret = await step.execute(mock_ctx)

        assert ret is True
        assert mock_ctx.should_stop is True
        mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_whitespace_reply_skips_save(mock_ctx: MagicMock) -> None:
    """纯空白 reply → should_stop=True，不调 _create_deliver_and_broadcast_reply_message。"""
    runtime_result = _make_result("template.fallback", "   ")

    with (
        patch("app.ai.entry.processor._get_assistant_service") as mock_get,
        patch("app.ai.entry.processor._create_deliver_and_broadcast_reply_message") as mock_save,
        patch("app.ai.entry.processor.bind_usage_context"),
    ):
        mock_svc = AsyncMock()
        mock_svc.process_message = AsyncMock(return_value=runtime_result)
        mock_get.return_value = mock_svc

        step = RunAssistantOrchestrator()
        await step.execute(mock_ctx)

        mock_save.assert_not_called()


# ══════════════════════════════════════════════
# 测试：metadata 包含必需字段
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_metadata_contains_required_fields(mock_ctx: MagicMock) -> None:
    """metadata 包含 ai_route / scenario_id / pending_directive / resource_trace / merged_customer_text。"""
    rt = ResourceTrace(skill_calls=["manage_order"], sql_calls=2)
    runtime_result = _make_result(
        "order.list",
        "您有 3 笔订单。",
        directive=PendingDirective.CLEAR,
        resource_trace=rt,
    )

    with (
        patch("app.ai.entry.processor._get_assistant_service") as mock_get,
        patch("app.ai.entry.processor._create_deliver_and_broadcast_reply_message") as mock_save,
        patch("app.ai.entry.processor.bind_usage_context"),
    ):
        mock_svc = AsyncMock()
        mock_svc.process_message = AsyncMock(return_value=runtime_result)
        mock_get.return_value = mock_svc

        step = RunAssistantOrchestrator()
        await step.execute(mock_ctx)

        args, kwargs = mock_save.call_args
        meta = kwargs["metadata"]
        assert meta["ai_route"] == "ASSISTANT_SERVICE"
        assert meta["scenario_id"] == "order.list"
        assert meta["pending_directive"] == "clear"
        assert meta["resource_trace"]["skill_calls"] == ["manage_order"]
        assert meta["resource_trace"]["sql_calls"] == 2
        assert meta["merged_customer_text"] == "你好"


# ══════════════════════════════════════════════
# 测试：order.create 返回 graph Pending 回复
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_order_create_graph_pending(mock_ctx: MagicMock) -> None:
    """order.create → 返回 graph Pending 回复，不报系统异常。"""
    mock_ctx.customer_text = "我要买一台 iPhone 15"

    runtime_result = _make_result(
        "order.create",
        "请选择要购买的商品：\n1. iPhone 15\n2. iPhone 15 Pro",
        directive=PendingDirective.SET,
    )

    with (
        patch("app.ai.entry.processor._get_assistant_service") as mock_get,
        patch("app.ai.entry.processor._create_deliver_and_broadcast_reply_message") as mock_save,
        patch("app.ai.entry.processor._mark_pending_human") as mock_mark,
        patch("app.ai.entry.processor.bind_usage_context"),
    ):
        mock_svc = AsyncMock()
        mock_svc.process_message = AsyncMock(return_value=runtime_result)
        mock_get.return_value = mock_svc

        step = RunAssistantOrchestrator()
        ret = await step.execute(mock_ctx)

        assert ret is True
        assert mock_ctx.should_stop is True
        mock_mark.assert_not_called()  # 非转人工
        mock_save.assert_awaited_once()
        args, kwargs = mock_save.call_args
        assert "iPhone" in args[2]
        assert kwargs["metadata"]["scenario_id"] == "order.create"
        assert kwargs["metadata"]["pending_directive"] == "set"


# ══════════════════════════════════════════════
# 测试：handler_result 为 None 时兼容
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_handler_result_none(mock_ctx: MagicMock) -> None:
    """handler_result 为 None 时 processor 不 panic。"""
    runtime_result = AssistantRuntimeResult(
        reply="回复内容",
        handler_result=None,
        metadata={"scenario_id": "template.fallback", "pending_directive": "CLEAR", "resource_trace": {}},
    )

    with (
        patch("app.ai.entry.processor._get_assistant_service") as mock_get,
        patch("app.ai.entry.processor._create_deliver_and_broadcast_reply_message") as mock_save,
        patch("app.ai.entry.processor.bind_usage_context"),
    ):
        mock_svc = AsyncMock()
        mock_svc.process_message = AsyncMock(return_value=runtime_result)
        mock_get.return_value = mock_svc

        step = RunAssistantOrchestrator()
        ret = await step.execute(mock_ctx)

        assert ret is True
        assert mock_ctx.should_stop is True
        mock_save.assert_awaited_once()
