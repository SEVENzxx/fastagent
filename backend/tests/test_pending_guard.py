"""PendingGuard + PendingService 单元测试。

覆盖：
  - PendingGuard 3 种返回（HUMAN / CANCEL / RESUME）
  - PendingService 3 种指令（SET / KEEP / CLEAR）
  - 坏数据处理（PendingStateCorruptedError）
  - PendingState 只保存 LangGraph 恢复信封
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.ai.assistant.pending_guard import PendingGuard
from app.ai.context.pending_service import PendingService
from app.ai.context.pending_state import (
    PendingAction,
    PendingDirective,
    PendingState,
    PendingStateCorruptedError,
)


@pytest.fixture
def pending_state() -> PendingState:
    return PendingState(
        scenario_id="order.create",
        step="collect_missing_info",
        graph_thread_id="thread-1",
        interrupt_id="interrupt-1",
    )


@pytest.fixture
def guard() -> PendingGuard:
    return PendingGuard()


@pytest.fixture
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(mock_redis: AsyncMock) -> PendingService:
    return PendingService(redis_client=mock_redis)


class TestPendingGuardBranches:
    """验证 PendingGuard.check() 三种返回。"""

    @pytest.mark.asyncio
    async def test_human_transfer(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """HUMAN: 转人工请求优先级最高。"""
        assert await guard.check("转人工", None, pending_state) == PendingAction.HUMAN
        assert await guard.check("我要找人工客服", None, pending_state) == PendingAction.HUMAN
        assert await guard.check("给我转人工", None, pending_state) == PendingAction.HUMAN

    @pytest.mark.asyncio
    async def test_human_exact_standalone(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """HUMAN: 单独“人工”精确匹配。"""
        assert await guard.check("人工", None, pending_state) == PendingAction.HUMAN

    @pytest.mark.asyncio
    async def test_human_not_ai(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """HUMAN: “人工智能”不应误触发转人工。"""
        assert await guard.check("人工智能", None, pending_state) != PendingAction.HUMAN

    @pytest.mark.asyncio
    async def test_cancel_exact(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """CANCEL: 精确匹配退出信号。"""
        for text in ("算了", "算了吧", "不要了", "不弄了", "不问了", "不用了", "不了"):
            assert await guard.check(text, None, pending_state) == PendingAction.CANCEL

    @pytest.mark.asyncio
    async def test_cancel_sole_cancel(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """CANCEL: 单独“取消”视为退出当前图流程。"""
        assert await guard.check("取消", None, pending_state) == PendingAction.CANCEL

    @pytest.mark.asyncio
    async def test_cancel_operation_phrases(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """CANCEL: 明确取消当前操作。"""
        assert await guard.check("取消一下", None, pending_state) == PendingAction.CANCEL
        assert await guard.check("取消这次操作", None, pending_state) == PendingAction.CANCEL
        assert await guard.check("取消当前操作", None, pending_state) == PendingAction.CANCEL

    @pytest.mark.asyncio
    async def test_cancel_buy_reject(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """CANCEL: 放弃购买属于退出图流程。"""
        for text in ("不买了", "不想要了", "先不要了"):
            assert await guard.check(text, None, pending_state) == PendingAction.CANCEL

    @pytest.mark.asyncio
    async def test_cancel_order_phrase_is_cancel(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """取消订单不再走新意图检测，PendingGuard 只负责退出当前图。"""
        assert await guard.check("取消订单", None, pending_state) == PendingAction.RESUME
        assert await guard.check("订单取消", None, pending_state) == PendingAction.RESUME
        assert await guard.check("取消我的订单", None, pending_state) == PendingAction.RESUME

    @pytest.mark.asyncio
    async def test_resume_normal_reply(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """RESUME: 普通回复交给图恢复处理。"""
        for text in ("第一个", "1", "我要黑色的", "可以", "好的", "有什么优惠活动吗"):
            assert await guard.check(text, None, pending_state) == PendingAction.RESUME

    @pytest.mark.asyncio
    async def test_check_signature_matches_docs(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """check() 签名保持为 check(message, context, pending)。"""
        assert await guard.check("第一个", {"dummy": True}, pending_state) == PendingAction.RESUME


class TestPendingGuardOrder:
    """验证 HUMAN > CANCEL > RESUME 优先级。"""

    @pytest.mark.asyncio
    async def test_human_before_cancel(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """转人工优先级高于取消。"""
        assert await guard.check("转人工 算了", None, pending_state) == PendingAction.HUMAN

    @pytest.mark.asyncio
    async def test_cancel_before_resume(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """取消优先级高于普通恢复。"""
        assert await guard.check("取消", None, pending_state) == PendingAction.CANCEL


class TestPendingServiceDirectives:
    """验证 PendingService.apply_directive() 三种指令。"""

    @pytest.mark.asyncio
    async def test_set_directive(self, service: PendingService, pending_state: PendingState) -> None:
        """SET: 调用 redis.set 写入。"""
        await service.apply_directive(
            tenant_id=1,
            conversation_id=1,
            directive=PendingDirective.SET,
            pending_state=pending_state,
        )
        service.redis.set.assert_awaited_once()
        assert service.redis.set.await_args[0][0] == service._key(1, 1)

    @pytest.mark.asyncio
    async def test_clear_directive(self, service: PendingService) -> None:
        """CLEAR: 调用 redis.delete 删除。"""
        await service.apply_directive(
            tenant_id=1,
            conversation_id=1,
            directive=PendingDirective.CLEAR,
        )
        service.redis.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_keep_directive(self, service: PendingService) -> None:
        """KEEP: 不做任何 Redis 写操作。"""
        await service.apply_directive(
            tenant_id=1,
            conversation_id=1,
            directive=PendingDirective.KEEP,
        )
        service.redis.set.assert_not_called()
        service.redis.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_without_state_raises(self, service: PendingService) -> None:
        """SET 不传 state 应抛出 ValueError。"""
        with pytest.raises(ValueError, match="SET 指令必须提供 pending_state"):
            await service.apply_directive(
                tenant_id=1,
                conversation_id=1,
                directive=PendingDirective.SET,
                pending_state=None,
            )


class TestPendingServiceIO:
    """验证 PendingService 读写和异常处理。"""

    @pytest.mark.asyncio
    async def test_get_none_when_missing(self, service: PendingService, mock_redis: AsyncMock) -> None:
        """key 不存在时返回 None。"""
        mock_redis.get.return_value = None
        assert await service.get(1, 1) is None

    @pytest.mark.asyncio
    async def test_get_success(self, service: PendingService, mock_redis: AsyncMock, pending_state: PendingState) -> None:
        """正常 JSON 可解析为 PendingState。"""
        mock_redis.get.return_value = json.dumps(pending_state.model_dump(mode="json"))
        result = await service.get(1, 1)
        assert result is not None
        assert result.scenario_id == pending_state.scenario_id
        assert result.step == pending_state.step
        assert result.graph_thread_id == pending_state.graph_thread_id

    @pytest.mark.asyncio
    async def test_get_corrupted_data_raises(self, service: PendingService, mock_redis: AsyncMock) -> None:
        """坏 JSON 抛出 PendingStateCorruptedError。"""
        mock_redis.get.return_value = "{bad json}"
        with pytest.raises(PendingStateCorruptedError):
            await service.get(1, 1)

    @pytest.mark.asyncio
    async def test_get_invalid_model_raises(self, service: PendingService, mock_redis: AsyncMock) -> None:
        """合法 JSON 但不符合 PendingState schema 也抛出错误。"""
        mock_redis.get.return_value = json.dumps({"scenario_id": 123})
        with pytest.raises(PendingStateCorruptedError):
            await service.get(1, 1)

    @pytest.mark.asyncio
    async def test_set_persists(self, service: PendingService, mock_redis: AsyncMock, pending_state: PendingState) -> None:
        """set 调用 redis.set 并序列化图恢复信封。"""
        await service.set(1, 1, pending_state)
        mock_redis.set.assert_awaited_once()
        call_args = mock_redis.set.await_args.args
        call_kwargs = mock_redis.set.await_args.kwargs
        payload = json.loads(call_args[1])
        assert call_args[0] == "pending:1:1"
        assert payload["scenario_id"] == "order.create"
        assert payload["graph_thread_id"] == "thread-1"
        assert "expected_response_type" not in payload
        assert call_kwargs.get("ex") == service.ttl_seconds

    @pytest.mark.asyncio
    async def test_clear_deletes(self, service: PendingService, mock_redis: AsyncMock) -> None:
        """clear 调用 redis.delete。"""
        await service.clear(1, 1)
        mock_redis.delete.assert_awaited_once_with("pending:1:1")