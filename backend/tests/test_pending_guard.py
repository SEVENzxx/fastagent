"""PendingGuard + PendingService 单元测试。

覆盖：
  - PendingGuard 4 种返回（HUMAN / CANCEL / NEW_INTENT / RESUME）
  - PendingService 3 种指令（SET / KEEP / CLEAR）
  - 坏数据处理（PendingStateCorruptedError）
  - 边界：取消订单→NEW_INTENT / 取消操作→CANCEL
  - 参数顺序与架构文档一致
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

import pytest

from app.ai.context.pending_state import (
    PendingAction,
    PendingDirective,
    PendingState,
    PendingStateCorruptedError,
)
from app.ai.context.pending_service import PendingService
from app.ai.assistant.pending_guard import PendingGuard


# ══════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════

@pytest.fixture
def pending_state() -> PendingState:
    return PendingState(
        scenario_id="product.detail",
        step="choose_product_candidate",
        expected_response_type="ordinal_or_text",
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
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


# ══════════════════════════════════════════════
# PendingGuard: 4 种分支
# ══════════════════════════════════════════════

class TestPendingGuardBranches:
    """验证 PendingGuard.check() 4 种返回。"""

    @pytest.mark.asyncio
    async def test_human_transfer(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """HUMAN: 转人工请求最高优先级。"""
        assert (await guard.check("转人工", None, pending_state)) == PendingAction.HUMAN
        assert (await guard.check("我要找人工客服", None, pending_state)) == PendingAction.HUMAN
        assert (await guard.check("给我转人工", None, pending_state)) == PendingAction.HUMAN

    @pytest.mark.asyncio
    async def test_human_exact_standalone(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """HUMAN: 单独"人工"精确匹配。"""
        assert (await guard.check("人工", None, pending_state)) == PendingAction.HUMAN

    @pytest.mark.asyncio
    async def test_human_not_ai(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """HUMAN: "人工智能"不应误触发转人工。"""
        result = await guard.check("人工智能", None, pending_state)
        assert result != PendingAction.HUMAN

    @pytest.mark.asyncio
    async def test_cancel_exact(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """CANCEL: 精确匹配退出信号。"""
        for text in ("算了", "算了吧", "不要了", "不弄了", "不问了", "不用了", "不了"):
            assert (await guard.check(text, None, pending_state)) == PendingAction.CANCEL, f"'{text}' 应返回 CANCEL"

    @pytest.mark.asyncio
    async def test_cancel_sole_cancel(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """CANCEL: 单独"取消"应视为退出信号。"""
        assert (await guard.check("取消", None, pending_state)) == PendingAction.CANCEL

    @pytest.mark.asyncio
    async def test_cancel_operation_phrases(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """CANCEL: "取消一下""取消这次操作"是退出当前 Pending。"""
        assert (await guard.check("取消一下", None, pending_state)) == PendingAction.CANCEL
        assert (await guard.check("取消这次操作", None, pending_state)) == PendingAction.CANCEL
        assert (await guard.check("取消当前操作", None, pending_state)) == PendingAction.CANCEL

    @pytest.mark.asyncio
    async def test_cancel_buy_reject(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """CANCEL: "不买了""不想要了"是退出信号。"""
        for text in ("不买了", "不想要了", "先不要了"):
            assert (await guard.check(text, None, pending_state)) == PendingAction.CANCEL, f"'{text}' 应返回 CANCEL"

    @pytest.mark.asyncio
    async def test_cancel_order_is_new_intent(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """取消订单不属于 CANCEL，应识别为 NEW_INTENT 的 order.cancel 场景。"""
        assert (await guard.check("取消订单", None, pending_state)) == PendingAction.NEW_INTENT
        assert (await guard.check("订单取消", None, pending_state)) == PendingAction.NEW_INTENT
        assert (await guard.check("取消我的订单", None, pending_state)) == PendingAction.NEW_INTENT

    @pytest.mark.asyncio
    async def test_new_intent_promotion(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """NEW_INTENT: 优惠/政策类提问。"""
        assert (await guard.check("有什么优惠活动吗", None, pending_state)) == PendingAction.NEW_INTENT

    @pytest.mark.asyncio
    async def test_new_intent_order_query(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """NEW_INTENT: 查订单。"""
        assert (await guard.check("查一下我的订单", None, pending_state)) == PendingAction.NEW_INTENT
        assert (await guard.check("我的订单", None, pending_state)) == PendingAction.NEW_INTENT

    @pytest.mark.asyncio
    async def test_new_intent_product_browse(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """NEW_INTENT: 商品浏览。"""
        assert (await guard.check("有什么商品推荐", None, pending_state)) == PendingAction.NEW_INTENT

    @pytest.mark.asyncio
    async def test_resume_normal_reply(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """RESUME: 普通回复应恢复 Pending。"""
        for text in ("第一个", "1", "我要黑色的", "可以", "好的"):
            assert (await guard.check(text, None, pending_state)) == PendingAction.RESUME, f"'{text}' 应返回 RESUME"

    @pytest.mark.asyncio
    async def test_check_signature_matches_docs(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """check() 签名: check(message, context, pending) 与架构文档一致。"""
        # 按 architecture.md 和 refactor-plan.md 的签名: check(message, context, pending)
        result = await guard.check("第一个", {"dummy": True}, pending_state)
        assert result == PendingAction.RESUME


# ══════════════════════════════════════════════
# PendingGuard: 检查顺序验证
# ══════════════════════════════════════════════

class TestPendingGuardOrder:
    """验证 HUMAN > CANCEL > NEW_INTENT > RESUME 优先级。"""

    @pytest.mark.asyncio
    async def test_human_before_cancel(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """转人工 优先级高于 取消。"""
        assert (await guard.check("转人工 算了", None, pending_state)) == PendingAction.HUMAN

    @pytest.mark.asyncio
    async def test_cancel_before_new_intent(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """取消 优先级高于 新意图。"""
        assert (await guard.check("取消", None, pending_state)) == PendingAction.CANCEL

    @pytest.mark.asyncio
    async def test_new_intent_before_resume(self, guard: PendingGuard, pending_state: PendingState) -> None:
        """明显新意图 优先级高于 RESUME（无匹配时应 RESUME）。"""
        assert (await guard.check("有什么优惠", None, pending_state)) == PendingAction.NEW_INTENT


# ══════════════════════════════════════════════
# PendingService: 3 种指令
# ══════════════════════════════════════════════

class TestPendingServiceDirectives:
    """验证 PendingService.apply_directive() 3 种指令。"""

    @pytest.mark.asyncio
    async def test_set_directive(self, service: PendingService, pending_state: PendingState) -> None:
        """SET: 应调用 redis.set 写入。"""
        await service.apply_directive(
            tenant_id=1, conversation_id=1,
            directive=PendingDirective.SET, pending_state=pending_state,
        )
        service.redis.set.assert_awaited_once()
        key = service._key(1, 1)
        assert service.redis.set.await_args[0][0] == key

    @pytest.mark.asyncio
    async def test_clear_directive(self, service: PendingService) -> None:
        """CLEAR: 应调用 redis.delete 删除。"""
        await service.apply_directive(
            tenant_id=1, conversation_id=1, directive=PendingDirective.CLEAR,
        )
        service.redis.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_keep_directive(self, service: PendingService) -> None:
        """KEEP: 不做任何操作。"""
        await service.apply_directive(
            tenant_id=1, conversation_id=1, directive=PendingDirective.KEEP,
        )
        service.redis.set.assert_not_called()
        service.redis.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_without_state_raises(self, service: PendingService) -> None:
        """SET 不传 state 应抛出 ValueError。"""
        with pytest.raises(ValueError, match="SET 指令必须提供 pending_state"):
            await service.apply_directive(
                tenant_id=1, conversation_id=1,
                directive=PendingDirective.SET, pending_state=None,
            )


# ══════════════════════════════════════════════
# PendingService: 读写与异常
# ══════════════════════════════════════════════

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

    @pytest.mark.asyncio
    async def test_get_corrupted_data_raises(self, service: PendingService, mock_redis: AsyncMock) -> None:
        """坏 JSON 抛出 PendingStateCorruptedError。"""
        mock_redis.get.return_value = "{bad json}"
        with pytest.raises(PendingStateCorruptedError):
            await service.get(1, 1)

    @pytest.mark.asyncio
    async def test_get_invalid_model_raises(self, service: PendingService, mock_redis: AsyncMock) -> None:
        """合法 JSON 但不符合 PendingState schema 也抛出 PendingStateCorruptedError。"""
        mock_redis.get.return_value = json.dumps({"scenario_id": 123})
        with pytest.raises(PendingStateCorruptedError):
            await service.get(1, 1)

    @pytest.mark.asyncio
    async def test_set_persists(self, service: PendingService, mock_redis: AsyncMock, pending_state: PendingState) -> None:
        """set 调用 redis.set 并序列化。"""
        await service.set(1, 1, pending_state)
        mock_redis.set.assert_awaited_once()
        call_args = mock_redis.set.await_args.args
        call_kwargs = mock_redis.set.await_args.kwargs
        assert call_args[0] == "pending:1:1"
        assert json.loads(call_args[1])["scenario_id"] == "product.detail"
        assert call_kwargs.get("ex") == service.ttl_seconds

    @pytest.mark.asyncio
    async def test_clear_deletes(self, service: PendingService, mock_redis: AsyncMock) -> None:
        """clear 调用 redis.delete。"""
        await service.clear(1, 1)
        mock_redis.delete.assert_awaited_once_with("pending:1:1")
