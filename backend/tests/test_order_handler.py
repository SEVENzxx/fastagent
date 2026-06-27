"""OrderHandler 单元测试。

覆盖 4 个只读订单场景 + 边界 + LangGraph 子图：
  1. order.list → 订单列表，不设置 active_order_id
  2. order.filter → 状态/时间组合过滤
  3. order.detail → 订单号/序号/上下文解析详情
  4. order.shipping_status → 物流查询
  5. 列表意图不解析 active_order_id
  6. 边界：空文本、无 contact_id、未注册场景
  7. 工具函数：_filter_by_time / _filter_orders / _parse_order_time / _get_order_id
  8. order.create / order.cancel LangGraph 子图（含持久化幂等/checkpointer 测试）
"""
from __future__ import annotations

import os

# 在 graph 模块 import 前设置测试模式（持久化 checkpointer 降级）
os.environ.setdefault("FASTAGENT_TEST_MODE", "1")

from collections.abc import Generator
from datetime import datetime, timezone, timedelta
from typing import Any

import pytest

from app.ai.components.order_reference import OrderReferenceResult
from app.ai.context.pending_state import PendingDirective
from app.ai.handlers.base import HandlerResult
from app.ai.handlers.order import (
    OrderHandler,
    _filter_by_time,
    _filter_orders,
    _get_order_id,
    _parse_order_time,
    _summarize_orders,
)
from app.ai.recognition.types import ScenarioDecision
from app.ai.reply_builders.order import OrderReplyBuilder
from app.ai.context.session_context import SessionContext
from app.ai.handlers.base import ToolResult
from app.ai.services.idempotency import IdempotencyService, order_idempotency
from app.common.trace.context import ensure_trace_id, get_trace_id, reset_trace_id
from unittest.mock import patch


@pytest.fixture(autouse=True)
def clear_idempotency_fallback() -> Generator[None, None, None]:
    """隔离 Redis 不可用时的内存幂等降级状态。"""
    old_redis = order_idempotency._redis
    old_in_memory = order_idempotency._in_memory
    order_idempotency._redis = None
    order_idempotency._in_memory = True
    IdempotencyService.clear_fallback()
    yield
    IdempotencyService.clear_fallback()
    order_idempotency._redis = old_redis
    order_idempotency._in_memory = old_in_memory


# ══════════════════════════════════════════════
# Fake OrderSkill
# ══════════════════════════════════════════════


class FakeOrderSkill:
    """内存 OrderSkill，不依赖数据库。"""

    orders: dict[int, dict[str, Any]] = {}
    call_log: list[dict[str, Any]] = []

    @classmethod
    def reset(cls) -> None:
        cls.orders = {}
        cls.call_log = []

    @classmethod
    def add_order(cls, order_id: int, **overrides: Any) -> None:
        defaults: dict[str, Any] = {
            "order_id": str(order_id),
            "status": "pending_customer_confirm",
            "status_label": "待确认",
            "payable_amount": 100.0,
            "total_amount": 100.0,
            "items": [
                {
                    "product_name": "测试商品",
                    "quantity": 1,
                    "subtotal": 100.0,
                    "unit_price": 100.0,
                },
            ],
            "shipping_address": None,
            "receiver_name": None,
            "receiver_phone": None,
            "missing_info": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "tenant_id": 1,
            "contact_id": 1,
        }
        defaults.update(overrides)
        cls.orders[order_id] = defaults

    @staticmethod
    async def create_order_draft(
        *,
        tenant_id: int,
        contact_id: int | None = None,
        db: Any = None,
        **kwargs: Any,
    ) -> ToolResult:
        """模拟创建订单草稿。"""
        _ = db
        items = kwargs.get("items") or []
        FakeOrderSkill.call_log.append({
            "method": "create_order_draft",
            "tenant_id": tenant_id,
            "contact_id": contact_id,
            **{k: v for k, v in kwargs.items() if k != "db"},
        })
        if not items:
            return ToolResult(
                ok=False,
                skill_name="create_order_draft",
                error="商品还没有确定",
                missing_arguments=["items"],
            )
        order_id = f"mock_{tenant_id}_{contact_id}"
        item = items[0]
        reply = "\n".join([
            "订单已创建（模拟）：",
            f"  商品：{item.get('product_name', '')} ×{item.get('quantity', 1)}",
            f"  订单号：#mock_{tenant_id}_{contact_id}",
        ])
        return ToolResult(
            ok=True,
            skill_name="create_order_draft",
            result={
                "order_id": order_id,
                "message": reply,
                "items": items,
                "status": "draft",
            },
        )

    @staticmethod
    async def cancel_order_draft(
        *,
        tenant_id: int,
        contact_id: int | None = None,
        db: Any = None,
        **kwargs: Any,
    ) -> ToolResult:
        """模拟取消订单草稿。"""
        _ = tenant_id, contact_id, db
        order_id = kwargs.get("order_id", "")
        return ToolResult(
            ok=True,
            skill_name="cancel_order_draft",
            result={
                "order_id": order_id,
                "message": f"订单 #{order_id} 已取消。",
            },
        )

    @staticmethod
    async def simulate_payment(
        *,
        tenant_id: int,
        contact_id: int | None = None,
        db: Any = None,
        **kwargs: Any,
    ) -> ToolResult:
        """模拟支付成功。"""
        _ = db
        order_id = kwargs.get("order_id", "")
        FakeOrderSkill.call_log.append({
            "method": "simulate_payment",
            "tenant_id": tenant_id,
            "contact_id": contact_id,
            "order_id": order_id,
        })
        return ToolResult(
            ok=True,
            skill_name="simulate_payment",
            result={"order_id": order_id, "status": "paid", "message": "订单已支付。"},
        )

    @staticmethod
    async def agent_approve(
        *,
        tenant_id: int,
        contact_id: int | None = None,
        db: Any = None,
        **kwargs: Any,
    ) -> ToolResult:
        """模拟坐席审批通过。"""
        _ = db
        order_id = kwargs.get("order_id", "")
        FakeOrderSkill.call_log.append({
            "method": "agent_approve",
            "tenant_id": tenant_id,
            "contact_id": contact_id,
            "order_id": order_id,
        })
        return ToolResult(
            ok=True,
            skill_name="agent_approve",
            result={
                "order_id": order_id,
                "status": "agent_confirmed",
                "message": "订单已审批通过。",
            },
        )

    @staticmethod
    async def arrange_shipping(
        *,
        tenant_id: int,
        contact_id: int | None = None,
        db: Any = None,
        **kwargs: Any,
    ) -> ToolResult:
        """模拟安排发货。"""
        _ = db
        order_id = kwargs.get("order_id", "")
        FakeOrderSkill.call_log.append({
            "method": "arrange_shipping",
            "tenant_id": tenant_id,
            "contact_id": contact_id,
            "order_id": order_id,
        })
        return ToolResult(
            ok=True,
            skill_name="arrange_shipping",
            result={"order_id": order_id, "status": "shipped", "message": "订单已发货。"},
        )

    @staticmethod
    async def manage_order(
        *,
        tenant_id: int,
        contact_id: int | None = None,
        db: Any = None,
        **kwargs: Any,
    ) -> ToolResult:
        """模拟 manage_order，支持 detail 和 list 两种模式。

        支持 filter_statuses / filter_time_ref / page_size 参数。
        支持 contact_id 校验。
        """
        _ = db
        FakeOrderSkill.call_log.append({
            "method": "manage_order",
            "tenant_id": tenant_id,
            "contact_id": contact_id,
            **{k: v for k, v in kwargs.items() if k != "db"},
        })

        order_id = kwargs.get("order_id")
        if order_id is not None:
            # Detail 模式（与真实 skill 对齐：强制 contact_id）
            order_id = int(order_id)
            if contact_id is None:
                return ToolResult(ok=False, skill_name="manage_order", error="请先确认客户身份后查询订单。")
            order = FakeOrderSkill.orders.get(order_id)
            if order is None:
                return ToolResult(ok=False, skill_name="manage_order", error=f"未找到订单 #{order_id}")
            if order.get("tenant_id") != tenant_id:
                return ToolResult(ok=False, skill_name="manage_order", error=f"未找到订单 #{order_id}")
            # contact_id 校验
            if order.get("contact_id") != contact_id:
                return ToolResult(ok=False, skill_name="manage_order", error=f"未找到订单 #{order_id}")
            return ToolResult(ok=True, skill_name="manage_order", result=order)

        # List 模式
        if contact_id is None:
            return ToolResult(ok=False, skill_name="manage_order", error="请提供订单号或确认客户身份")

        filter_statuses: list[str] | None = kwargs.get("filter_statuses")
        filter_time_ref: str | None = kwargs.get("filter_time_ref")
        single_status: str | None = kwargs.get("status")

        matching = [
            o for o in FakeOrderSkill.orders.values()
            if o.get("tenant_id") == tenant_id and o.get("contact_id") == contact_id
        ]
        matching.sort(key=lambda o: o.get("created_at", ""), reverse=True)

        # 在 fake 层应用过滤（与真实 skill 行为对齐）
        if single_status and not filter_statuses:
            matching = [o for o in matching if o.get("status") == single_status]
        if filter_statuses:
            status_set = set(filter_statuses)
            matching = [o for o in matching if o.get("status") in status_set]
        if filter_time_ref:
            matching = _filter_by_time(matching, filter_time_ref)

        limit = int(kwargs.get("page_size", 10))
        limited = matching[:limit]

        return ToolResult(ok=True, skill_name="manage_order", result={
            "orders": limited,
            "count": len(matching),
            "message": f"找到 {len(matching)} 个订单",
        })


# ══════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════


def make_decision(scenario_id: str, **extra: Any) -> ScenarioDecision:
    """构造 ScenarioDecision。"""
    entities: dict[str, Any] = {"raw_text": extra.pop("text", "")}
    entities.update(extra)
    return ScenarioDecision(
        scenario_id=scenario_id,
        confidence=1.0,
        entities=entities,
    )


def make_context(**overrides: Any) -> SessionContext:
    """构造 SessionContext。"""
    defaults: dict[str, Any] = {
        "tenant_id": 1,
        "conversation_id": 1,
        "contact_id": 1,
    }
    defaults.update(overrides)
    return SessionContext(**defaults)


# ══════════════════════════════════════════════
# 1. order.list
# ══════════════════════════════════════════════


class TestOrderList:
    """订单列表：查订单 / 查看我的订单。"""

    @pytest.mark.asyncio
    async def test_view_my_orders(self) -> None:
        """"查看我的订单" → 返回列表，不设置 active_order_id。"""
        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(101, status="shipped", status_label="已发货")
        FakeOrderSkill.add_order(102, status="pending_customer_confirm", status_label="待确认")

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.list", text="查看我的订单")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.list"
        assert result.pending_directive == PendingDirective.CLEAR
        assert "共" in result.reply
        assert "订单 #101" in result.reply or "订单 #102" in result.reply
        # 不设置 active_order_id
        assert "active_order_id" not in result.context_update
        # 更新 recent_orders
        assert "recent_orders" in result.context_update
        assert len(result.context_update["recent_orders"]) == 2

    @pytest.mark.asyncio
    async def test_list_all_orders(self) -> None:
        """"查订单" → 返回列表。"""
        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(101, status="shipped", status_label="已发货")

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.list", text="查订单")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.list"
        assert result.pending_directive == PendingDirective.CLEAR
        assert "订单 #101" in result.reply
        assert "active_order_id" not in result.context_update

    @pytest.mark.asyncio
    async def test_list_with_active_order_id(self) -> None:
        """active_order_id 存在时，"查看我的订单" 不设置 active_order_id。"""
        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(101, status="shipped", status_label="已发货")

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context(active_order_id="20240614001")
        decision = make_decision("order.list", text="查看我的订单")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.list"
        assert "active_order_id" not in result.context_update

    @pytest.mark.asyncio
    async def test_no_orders(self) -> None:
        """无订单时返回"暂无订单"。"""
        FakeOrderSkill.reset()

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.list", text="查订单")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.list"
        assert "暂无" in result.reply
        assert result.pending_directive == PendingDirective.CLEAR

    @pytest.mark.asyncio
    async def test_no_contact_id(self) -> None:
        """无 contact_id 时提示确认客户身份。"""
        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(101)

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context(contact_id=None)
        decision = make_decision("order.list", text="查订单")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.list"
        assert "客户身份" in result.reply
        assert result.pending_directive == PendingDirective.CLEAR


# ══════════════════════════════════════════════
# 2. order.filter
# ══════════════════════════════════════════════


class TestOrderFilter:
    """订单筛选：状态 + 时间组合过滤。"""

    @pytest.mark.asyncio
    async def test_unshipped_filter(self) -> None:
        """"未发货的订单" → 只显示未发货组内的订单。"""
        FakeOrderSkill.reset()
        # unshipped 组: pending_customer_confirm, customer_confirmed, agent_confirmed
        FakeOrderSkill.add_order(101, status="pending_customer_confirm", status_label="待确认")
        FakeOrderSkill.add_order(102, status="shipped", status_label="已发货")
        FakeOrderSkill.add_order(103, status="cancelled", status_label="已取消")

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.filter", text="未发货的订单")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.filter"
        assert result.pending_directive == PendingDirective.CLEAR
        # 应有 101，没有 102、103
        assert "订单 #101" in result.reply
        assert "订单 #102" not in result.reply
        assert "订单 #103" not in result.reply

    @pytest.mark.asyncio
    async def test_cancelled_filter(self) -> None:
        """"已取消的订单" → 只显示已取消。"""
        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(101, status="pending_customer_confirm", status_label="待确认")
        FakeOrderSkill.add_order(102, status="cancelled", status_label="已取消")

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.filter", text="已取消的订单")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.filter"
        assert "订单 #102" in result.reply
        assert "订单 #101" not in result.reply

    @pytest.mark.asyncio
    async def test_unshipped_today(self) -> None:
        """"今天还没发货的订单" → 状态 + 时间组合过滤。"""
        FakeOrderSkill.reset()
        now = datetime.now(timezone.utc)
        yesterday = (now - timedelta(days=1)).isoformat()
        FakeOrderSkill.add_order(
            101, status="pending_customer_confirm",
            status_label="待确认", created_at=now.isoformat(),
        )
        FakeOrderSkill.add_order(
            102, status="pending_customer_confirm",
            status_label="待确认", created_at=yesterday,
        )
        FakeOrderSkill.add_order(
            103, status="shipped",
            status_label="已发货", created_at=now.isoformat(),
        )

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.filter", text="今天还没发货的订单")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.filter"
        # 101: 今天 + 未发货 ✓
        assert "订单 #101" in result.reply
        # 102: 昨天 + 未发货 ✗（不是今天）
        # 103: 今天 + 已发货 ✗（不是未发货）
        assert "订单 #102" not in result.reply
        assert "订单 #103" not in result.reply

    @pytest.mark.asyncio
    async def test_no_match(self) -> None:
        """过滤无结果。"""
        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(101, status="shipped", status_label="已发货")

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.filter", text="已取消的订单")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.filter"
        assert "暂无" in result.reply

    @pytest.mark.asyncio
    async def test_no_contact_id(self) -> None:
        """无 contact_id 时提示。"""
        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(101)

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context(contact_id=None)
        decision = make_decision("order.filter", text="未发货的订单")

        result = await handler.execute(decision, ctx)

        assert "客户身份" in result.reply

    @pytest.mark.asyncio
    async def test_filter_more_than_five_results(self) -> None:
        """超过5条时，符合 status/time_ref 条件的第6条也能被查出。"""
        FakeOrderSkill.reset()
        now = datetime.now(timezone.utc)
        # 6 个未发货 (pending_customer_confirm)
        for i in range(1, 7):
            FakeOrderSkill.add_order(
                100 + i,
                status="pending_customer_confirm",
                status_label="待确认",
                created_at=now.isoformat(),
            )
        # 4 个已取消（不应出现在未发货过滤中）
        for i in range(7, 11):
            FakeOrderSkill.add_order(
                100 + i,
                status="cancelled",
                status_label="已取消",
                created_at=now.isoformat(),
            )

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.filter", text="未发货的订单")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.filter"
        assert result.pending_directive == PendingDirective.CLEAR
        # 全部 6 个未发货都应出现
        for i in range(1, 7):
            assert f"订单 #10{i}" in result.reply
        # 已取消的不应出现
        assert "订单 #107" not in result.reply

    @pytest.mark.asyncio
    async def test_filter_beyond_100_results(self) -> None:
        """超过100条时，第101条符合"今天还没发货"也能查出。"""
        FakeOrderSkill.reset()
        now = datetime.now(timezone.utc)
        today = now.isoformat()
        yesterday = (now - timedelta(days=1)).isoformat()
        # 100 个已发货（今天）
        for i in range(1, 101):
            FakeOrderSkill.add_order(
                1000 + i,
                status="shipped", status_label="已发货",
                created_at=today,
            )
        # 1 个未发货（今天）— 第 101 条
        FakeOrderSkill.add_order(
            10101, status="pending_customer_confirm",
            status_label="待确认", created_at=today,
        )
        # 1 个未发货（昨天）— 不应出现
        FakeOrderSkill.add_order(
            10102, status="pending_customer_confirm",
            status_label="待确认", created_at=yesterday,
        )

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.filter", text="今天还没发货的订单")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.filter"
        assert result.pending_directive == PendingDirective.CLEAR
        # 第 101 条（今天未发货）应出现
        assert "订单 #10101" in result.reply
        # 昨天的未发货不应出现
        assert "订单 #10102" not in result.reply


# ══════════════════════════════════════════════
# 3. order.detail
# ══════════════════════════════════════════════


class TestOrderDetail:
    """订单详情：订单号/序号/上下文。"""

    @pytest.mark.asyncio
    async def test_cross_contact_cannot_access(self) -> None:
        """同租户不同 contact 不能查到对方订单详情。"""
        FakeOrderSkill.reset()
        # Order owned by contact_id=2
        FakeOrderSkill.add_order(
            20240614001, status="shipped", status_label="已发货",
            contact_id=2,
        )

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context(contact_id=1)  # Different contact
        decision = make_decision("order.detail", text="订单号20240614001")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.detail"
        assert "未找到" in result.reply

    @pytest.mark.asyncio
    async def test_contact_id_none_rejects_detail(self) -> None:
        """contact_id=None + 订单号 → 提示确认客户身份，不返回详情。"""
        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(20240614001, status="shipped", status_label="已发货")

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context(contact_id=None)
        decision = make_decision("order.detail", text="订单号20240614001")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.detail"
        assert "客户身份" in result.reply
        # 不应返回详情内容
        assert "已发货" not in result.reply

    @pytest.mark.asyncio
    async def test_order_number(self) -> None:
        """"订单号20240614001" → 解析到订单详情，设置 active_order_id。"""
        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(
            20240614001, status="shipped", status_label="已发货",
            payable_amount=299.0,
        )

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.detail", text="订单号20240614001")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.detail"
        assert result.pending_directive == PendingDirective.CLEAR
        assert "已发货" in result.reply
        assert result.context_update.get("active_order_id") == "20240614001"

    @pytest.mark.asyncio
    async def test_ordinal_first(self) -> None:
        """"第一个" → 从 recent_orders 解析到订单详情。"""
        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(
            111, status="pending_customer_confirm", status_label="待确认",
        )
        FakeOrderSkill.add_order(
            222, status="shipped", status_label="已发货",
        )

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context(
            recent_orders=[
                {"id": "111", "status": "pending_customer_confirm"},
                {"id": "222", "status": "shipped"},
            ],
        )
        decision = make_decision("order.detail", text="第一个")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.detail"
        assert result.pending_directive == PendingDirective.CLEAR
        # 应查到 order 111
        assert result.context_update.get("active_order_id") == "111"

    @pytest.mark.asyncio
    async def test_ordinal_out_of_range(self) -> None:
        """序号超出范围 → fallback 到列表。"""
        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(111, status="pending_customer_confirm")

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context(
            recent_orders=[{"id": "111", "status": "pending_customer_confirm"}],
        )
        decision = make_decision("order.detail", text="第三个订单")

        result = await handler.execute(decision, ctx)

        # fallback 到列表
        assert result.scenario_id == "order.detail"
        assert result.reply
        assert "active_order_id" not in result.context_update

    @pytest.mark.asyncio
    async def test_active_reference(self) -> None:
        """active_order_id + 指代 → 解析到订单详情。"""
        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(
            12345678901, status="pending_customer_confirm", status_label="待确认",
        )

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context(active_order_id="12345678901")
        decision = make_decision("order.detail", text="这个订单怎么样了")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.detail"
        assert result.pending_directive == PendingDirective.CLEAR
        assert result.context_update.get("active_order_id") == "12345678901"

    @pytest.mark.asyncio
    async def test_order_not_found(self) -> None:
        """不存在的订单号 → 提示未找到。"""
        FakeOrderSkill.reset()
        # 不添加任何订单

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.detail", text="订单号99999999")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.detail"
        assert "未找到" in result.reply or "不存在" in result.reply


# ══════════════════════════════════════════════
# 4. order.shipping_status
# ══════════════════════════════════════════════


class TestOrderShippingStatus:
    """物流/发货状态查询。"""

    @pytest.mark.asyncio
    async def test_shipping_enquiry_with_deixis(self) -> None:
        """"这个什么时候发货" → 解析 active_order，返回物流状态。"""
        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(
            20240614001, status="shipped", status_label="已发货",
        )

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context(active_order_id="20240614001")
        decision = make_decision("order.shipping_status", text="这个什么时候发货")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.shipping_status"
        assert result.pending_directive == PendingDirective.CLEAR
        assert "已发货" in result.reply or "运输" in result.reply
        assert result.context_update.get("active_order_id") == "20240614001"

    @pytest.mark.asyncio
    async def test_shipping_enquiry_bare(self) -> None:
        """"发货了吗" → 解析 active_order。"""
        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(
            20240614001, status="pending_customer_confirm", status_label="待确认",
        )

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context(active_order_id="20240614001")
        decision = make_decision("order.shipping_status", text="发货了吗")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.shipping_status"
        assert result.pending_directive == PendingDirective.CLEAR
        assert "待确认" in result.reply or "尚未发货" in result.reply
        assert result.context_update.get("active_order_id") == "20240614001"

    @pytest.mark.asyncio
    async def test_logistics_enquiry_no_active(self) -> None:
        """无 active_order_id 时 → fallback 到列表。"""
        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(101, status="shipped", status_label="已发货")

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.shipping_status", text="物流到哪了")

        result = await handler.execute(decision, ctx)

        # fallback 到列表
        assert result.scenario_id == "order.shipping_status"
        assert result.reply
        # 没有 active_order_id（因为是 fallback）
        assert "active_order_id" not in result.context_update

    @pytest.mark.asyncio
    async def test_shipping_cross_contact_cannot_access(self) -> None:
        """物流查询同租户不同 contact 不能查到对方订单。"""
        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(
            20240614001, status="shipped", status_label="已发货",
            contact_id=2,
        )

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context(contact_id=1, active_order_id="20240614001")
        decision = make_decision("order.shipping_status", text="发货了吗")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.shipping_status"
        assert "未找到" in result.reply

    @pytest.mark.asyncio
    async def test_contact_id_none_rejects_shipping(self) -> None:
        """contact_id=None + 订单号+物流查询 → 提示确认客户身份，不返回物流。"""
        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(20240614001, status="shipped", status_label="已发货")

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context(contact_id=None)
        decision = make_decision("order.shipping_status", text="订单号20240614001什么时候发货")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.shipping_status"
        assert "客户身份" in result.reply
        # 不应返回物流内容
        assert "已发货" not in result.reply


# ══════════════════════════════════════════════
# 5. 列表意图不清除 active_order_id
# ══════════════════════════════════════════════


class TestListIntentWithActive:
    """列表意图不解析 active_order_id。"""

    @pytest.mark.asyncio
    async def test_list_ignores_active_order_id(self) -> None:
        """active_order_id 存在时，"查看我的订单" 不覆盖 active_order_id。"""
        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(101, status="shipped", status_label="已发货")

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context(active_order_id="20240614001")
        decision = make_decision("order.list", text="查看我的订单")

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.list"
        # 不应在 context_update 中设置 active_order_id
        assert "active_order_id" not in result.context_update
        # 更新 recent_orders
        assert "recent_orders" in result.context_update


# ══════════════════════════════════════════════
# 6. 未实现场景 + 边界
# ══════════════════════════════════════════════


class TestOrderCreationGraph:
    """order.create 使用 OrderCreationGraph。"""

    @pytest.mark.asyncio
    async def test_create_first_turn_returns_set(self) -> None:
        """首次下单 → SET graph PendingState（缺收货地址中断）。"""
        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.create", text="买耳机")
        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.create"
        assert result.pending_directive == PendingDirective.SET
        assert result.pending_state is not None
        assert result.pending_state.mode == "graph"
        assert result.pending_state.scenario_id == "order.create"
        # 首轮应中断在商品确认节点
        assert "确认" in result.reply and "商品" in result.reply

    @pytest.mark.asyncio
    async def test_create_resume_duplicate_order_start_keeps_pending(self) -> None:
        """已有下单 Pending 时重复发起下单 → KEEP 当前流程，不喂给图。"""
        FakeOrderSkill.reset()
        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.create", text="买耳机")

        result1 = await handler.execute(decision, ctx)
        assert result1.pending_state is not None

        result2 = await handler.resume(result1.pending_state, "下单键盘", ctx)

        assert result2.pending_directive == PendingDirective.KEEP
        assert "未完成" in result2.reply
        assert not [
            call for call in FakeOrderSkill.call_log
            if call.get("method") == "create_order_draft"
        ]

    @pytest.mark.asyncio
    async def test_create_start_short_lock_blocks_duplicate_graph_start(self) -> None:
        """入口短锁命中时，第二次新下单不会再创建新的图线程。"""
        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()

        result1 = await handler.execute(make_decision("order.create", text="买耳机"), ctx)
        result2 = await handler.execute(make_decision("order.create", text="下单键盘"), ctx)

        assert result1.pending_directive == PendingDirective.SET
        assert result2.pending_directive == PendingDirective.CLEAR
        assert "已经在处理" in result2.reply

    @pytest.mark.asyncio
    async def test_create_full_flow(self) -> None:
        """下单完整流程：首轮→补地址→确认→完成。"""
        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.create", text="买耳机")

        result1 = await handler.execute(decision, ctx)
        assert result1.pending_directive == PendingDirective.SET
        assert result1.pending_state is not None

        # 确认商品
        result2 = await handler.resume(result1.pending_state, "确认", ctx)
        assert result2.pending_directive == PendingDirective.SET
        assert result2.pending_state is not None

        # 补地址和电话
        result3 = await handler.resume(result2.pending_state, "北京市朝阳区 13800138000", ctx)
        assert result3.pending_directive == PendingDirective.SET
        assert result3.pending_state is not None

        # 汇总确认下单
        result4 = await handler.resume(result3.pending_state, "确认", ctx)
        assert result4.pending_directive == PendingDirective.CLEAR
        assert result4.pending_state is None
        assert "订单" in result4.reply or "耳机" in result4.reply

    @pytest.mark.asyncio
    async def test_create_cancel_during_confirm(self) -> None:
        """确认阶段取消 → 不下单。"""
        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.create", text="买耳机")

        result1 = await handler.execute(decision, ctx)
        assert result1.pending_state is not None

        # 补地址
        result2 = await handler.resume(result1.pending_state, "北京市朝阳区", ctx)
        assert result2.pending_state is not None

        # 取消下单
        result3 = await handler.resume(result2.pending_state, "取消", ctx)
        assert result3.pending_directive == PendingDirective.CLEAR
        assert "取消" in result3.reply

    @pytest.mark.asyncio
    async def test_create_empty_text(self) -> None:
        """空文本 → 提示输入。"""
        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.create", text="")
        result = await handler.execute(decision, ctx)

        assert result.pending_directive == PendingDirective.CLEAR
        assert "商品" in result.reply or "描述" in result.reply

    @pytest.mark.asyncio
    async def test_create_idempotent_resume(self) -> None:
        """重复 resume 已完成图 → 不重复执行，返回安全提示。"""
        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.create", text="买耳机")

        result1 = await handler.execute(decision, ctx)
        assert result1.pending_state is not None
        ps = result1.pending_state

        # 确认商品
        result2 = await handler.resume(ps, "确认", ctx)
        assert result2.pending_state is not None
        ps = result2.pending_state

        # 补地址和电话
        result3 = await handler.resume(ps, "北京市朝阳区 13800138000", ctx)
        assert result3.pending_state is not None
        ps = result3.pending_state

        # 汇总确认 → 完成
        result4 = await handler.resume(ps, "确认", ctx)
        assert result4.pending_directive == PendingDirective.CLEAR
        assert "订单" in result4.reply

        # 用相同 pending_state 再次 resume → 不重复执行
        result5 = await handler.resume(ps, "确认", ctx)
        assert result5.pending_directive == PendingDirective.CLEAR
        assert result5.pending_state is None
        assert "请勿重复" in result5.reply


# ══════════════════════════════════════════════
# 6. Graph Resume trace_id 生命周期
# ══════════════════════════════════════════════


class TestGraphResumeTraceId:
    """Graph resume 链路的 trace_id 生命周期。

    注意：trace_id 通过 ContextVar 随 async task 自然继承（zero-copy），
    无需在 resume 路径中额外设置。这里验证继承链路的完整性。
    """

    @pytest.mark.asyncio
    async def test_create_resume_preserves_trace_id(self) -> None:
        """order.create resume 期间 trace_id 非空且持久。"""
        reset_trace_id()
        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.create", text="买耳机")

        result1 = await handler.execute(decision, ctx)
        assert result1.pending_state is not None

        test_tid = ensure_trace_id()

        original = OrderHandler._invoke_graph

        async def _spy_invoke(graph, initial_state, config, resume_message):
            assert get_trace_id() != "", "graph invoke 期间 trace_id 不应为空"
            assert get_trace_id() == test_tid
            return await original(graph, initial_state, config, resume_message)

        with patch.object(OrderHandler, "_invoke_graph", _spy_invoke):
            result2 = await handler.resume(result1.pending_state, "北京市朝阳区", ctx)

        assert get_trace_id() == test_tid, "resume 结束后 trace_id 应保持"
        reset_trace_id()

    @pytest.mark.asyncio
    async def test_cancel_resume_preserves_trace_id(self) -> None:
        """order.cancel resume 期间 trace_id 非空且持久。"""
        reset_trace_id()
        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.cancel", text="取消订单 123456789012345")

        result1 = await handler.execute(decision, ctx)
        assert result1.pending_state is not None

        test_tid = ensure_trace_id()

        original = OrderHandler._invoke_graph

        async def _spy_invoke(graph, initial_state, config, resume_message):
            assert get_trace_id() != ""
            assert get_trace_id() == test_tid
            return await original(graph, initial_state, config, resume_message)

        with patch.object(OrderHandler, "_invoke_graph", _spy_invoke):
            result2 = await handler.resume(result1.pending_state, "确认", ctx)

        assert get_trace_id() == test_tid, "resume 结束后 trace_id 应保持"
        reset_trace_id()


class TestOrderCancelGraph:
    """order.cancel 使用 OrderCancelGraph。"""

    @pytest.mark.asyncio
    async def test_cancel_first_turn_with_order_id(self) -> None:
        """取消含订单号 → SET graph PendingState（确认中断）。"""
        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.cancel", text="取消订单 123456789012345")
        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.cancel"
        assert result.pending_directive == PendingDirective.SET
        assert result.pending_state is not None
        assert result.pending_state.mode == "graph"
        # 确认取消中断
        assert "确认" in result.reply or "取消" in result.reply

    @pytest.mark.asyncio
    async def test_cancel_full_flow(self) -> None:
        """取消完整流程：首轮→确认→完成。"""
        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.cancel", text="取消订单 123456789012345")

        result1 = await handler.execute(decision, ctx)
        assert result1.pending_directive == PendingDirective.SET
        assert result1.pending_state is not None

        # 确认取消
        result2 = await handler.resume(result1.pending_state, "确认", ctx)
        assert result2.pending_directive == PendingDirective.CLEAR
        assert result2.pending_state is None
        assert "取消" in result2.reply

    @pytest.mark.asyncio
    async def test_cancel_abort_during_confirm(self) -> None:
        """确认阶段放弃 → 不取消。"""
        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.cancel", text="取消订单 123456789012345")

        result1 = await handler.execute(decision, ctx)
        assert result1.pending_state is not None

        result2 = await handler.resume(result1.pending_state, "不取消", ctx)
        assert result2.pending_directive == PendingDirective.CLEAR
        assert "保持" in result2.reply or "不变" in result2.reply

    @pytest.mark.asyncio
    async def test_cancel_empty_text(self) -> None:
        """空文本 → 提示输入。"""
        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.cancel", text="")
        result = await handler.execute(decision, ctx)

        assert result.pending_directive == PendingDirective.CLEAR
        assert "订单号" in result.reply

    @pytest.mark.asyncio
    async def test_cancel_no_order_id_in_text(self) -> None:
        """文本无订单号 → 提示补充。"""
        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.cancel", text="我要取消订单")
        result = await handler.execute(decision, ctx)

        assert result.pending_directive == PendingDirective.CLEAR
        assert "订单号" in result.reply

    @pytest.mark.asyncio
    async def test_cancel_idempotent_resume(self) -> None:
        """重复 resume 已完成取消图 → 不重复执行。"""
        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.cancel", text="取消订单 123456789012345")

        result1 = await handler.execute(decision, ctx)
        assert result1.pending_state is not None
        ps = result1.pending_state

        # 确认取消 → 完成
        result2 = await handler.resume(ps, "确认", ctx)
        assert result2.pending_directive == PendingDirective.CLEAR
        assert "取消" in result2.reply

        # 用相同 pending_state 再次 resume → 不重复执行
        result3 = await handler.resume(ps, "确认", ctx)
        assert result3.pending_directive == PendingDirective.CLEAR
        assert result3.pending_state is None
        assert "请勿重复" in result3.reply


class TestConfirmUnimplemented:
    """order.confirm 仍为骨架。"""

    @pytest.mark.asyncio
    async def test_confirm_placeholder(self) -> None:
        """order.confirm → 返回"开发中"。"""
        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.confirm", text="确认订单")
        result = await handler.execute(decision, ctx)
        assert "开发中" in result.reply

    @pytest.mark.asyncio
    async def test_unhandled_scenario(self) -> None:
        """未识别的 order.* 场景 → 返回"开发中"。"""
        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context()
        decision = make_decision("order.unknown", text="测试")
        result = await handler.execute(decision, ctx)
        assert "开发中" in result.reply


class TestEdgeCases:
    """边界情况。"""

    @pytest.mark.asyncio
    async def test_empty_text_falls_back(self) -> None:
        """raw_text 为空时 fallback 到 ctx.last_user_message。"""
        FakeOrderSkill.reset()
        FakeOrderSkill.add_order(101, status="shipped", status_label="已发货")

        handler = OrderHandler(skill=FakeOrderSkill)
        ctx = make_context(last_user_message="查订单")
        entities: dict[str, Any] = {}
        decision = ScenarioDecision(
            scenario_id="order.list", confidence=1.0, entities=entities,
        )

        result = await handler.execute(decision, ctx)

        assert result.scenario_id == "order.list"
        assert result.reply
        assert result.pending_directive == PendingDirective.CLEAR

    @pytest.mark.asyncio
    async def test_resume_simple_pending_falls_back(self) -> None:
        """simple mode Pending（非 graph）→ 兜底回复。"""
        from app.ai.context.pending_state import PendingState

        handler = OrderHandler(skill=FakeOrderSkill)
        pending = PendingState(
            scenario_id="order.list",
            step="choose",
            expected_response_type="text",
            mode="simple",
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        result = await handler.resume(pending, "1", make_context())
        assert result.reply
        assert result.pending_directive == PendingDirective.CLEAR

    @pytest.mark.asyncio
    async def test_default_resolver_created_when_not_injected(self) -> None:
        """未注入 resolver 时 _get_resolver 使用默认 resolver（不应抛异常）。"""
        handler = OrderHandler(skill=FakeOrderSkill)  # resolver=None
        ctx = make_context()
        decision = make_decision("order.list", text="查订单")
        # 不应抛出异常
        result = await handler.execute(decision, ctx)
        assert result.reply
        assert result.pending_directive == PendingDirective.CLEAR


# ══════════════════════════════════════════════
# 7. 工具函数单元测试
# ══════════════════════════════════════════════


class TestFilterOrders:
    """_filter_orders 工具函数。"""

    def _make_order(self, order_id: int, status: str, **overrides: Any) -> dict[str, Any]:
        order: dict[str, Any] = {
            "order_id": str(order_id),
            "status": status,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        order.update(overrides)
        return order

    def test_filter_by_status_group(self) -> None:
        orders = [
            self._make_order(1, "pending_customer_confirm"),
            self._make_order(2, "shipped"),
            self._make_order(3, "cancelled"),
        ]
        filtered = _filter_orders(orders, statuses=["pending_customer_confirm", "customer_confirmed"])
        assert len(filtered) == 1
        assert filtered[0]["order_id"] == "1"

    def test_filter_by_single_status(self) -> None:
        orders = [
            self._make_order(1, "pending_customer_confirm"),
            self._make_order(2, "shipped"),
        ]
        filtered = _filter_orders(orders, single_status="shipped")
        assert len(filtered) == 1
        assert filtered[0]["order_id"] == "2"

    def test_filter_no_match(self) -> None:
        orders = [self._make_order(1, "shipped")]
        filtered = _filter_orders(orders, statuses=["cancelled"])
        assert len(filtered) == 0

    def test_filter_no_filters(self) -> None:
        orders = [self._make_order(1, "shipped"), self._make_order(2, "cancelled")]
        filtered = _filter_orders(orders)
        assert len(filtered) == 2

    def test_filter_status_group_takes_priority(self) -> None:
        """statuses 和 single_status 都传时，只使用 statuses。"""
        orders = [
            self._make_order(1, "pending_customer_confirm"),
            self._make_order(2, "cancelled"),
        ]
        filtered = _filter_orders(orders, statuses=["cancelled"], single_status="pending_customer_confirm")
        # statuses 优先：只保留 cancelled
        assert len(filtered) == 1
        assert filtered[0]["order_id"] == "2"


class TestFilterByTime:
    """_filter_by_time 工具函数。"""

    def _make_ts(self, **offset: Any) -> str:
        return (datetime.now(timezone.utc) - timedelta(**offset)).isoformat()

    def _make_order(self, order_id: int, **overrides: Any) -> dict[str, Any]:
        order: dict[str, Any] = {
            "order_id": str(order_id),
            "status": "shipped",
            "created_at": self._make_ts(days=0),
        }
        order.update(overrides)
        return order

    def test_filter_today(self) -> None:
        now = datetime.now(timezone.utc)
        orders = [
            {"order_id": "1", "created_at": now.isoformat()},
            {"order_id": "2", "created_at": (now - timedelta(days=1)).isoformat()},
        ]
        filtered = _filter_by_time(orders, "today")
        assert len(filtered) == 1
        assert filtered[0]["order_id"] == "1"

    def test_filter_yesterday(self) -> None:
        now = datetime.now(timezone.utc)
        orders = [
            {"order_id": "1", "created_at": now.isoformat()},
            {"order_id": "2", "created_at": (now - timedelta(days=1)).isoformat()},
        ]
        filtered = _filter_by_time(orders, "yesterday")
        assert len(filtered) == 1
        assert filtered[0]["order_id"] == "2"

    def test_filter_this_month(self) -> None:
        now = datetime.now(timezone.utc)
        orders = [
            {"order_id": "1", "created_at": now.isoformat()},
            # 60 天前 → 不在本月
            {"order_id": "2", "created_at": (now - timedelta(days=60)).isoformat()},
        ]
        filtered = _filter_by_time(orders, "this_month")
        assert len(filtered) == 1
        assert filtered[0]["order_id"] == "1"

    def test_filter_recent(self) -> None:
        now = datetime.now(timezone.utc)
        orders = [
            {"order_id": "1", "created_at": now.isoformat()},
            # 30 天前 → 不在最近 7 天
            {"order_id": "2", "created_at": (now - timedelta(days=30)).isoformat()},
        ]
        filtered = _filter_by_time(orders, "recent")
        assert len(filtered) == 1
        assert filtered[0]["order_id"] == "1"

    def test_parse_order_time_fallback(self) -> None:
        """无 created_at 时返回 datetime.min。"""
        order: dict[str, Any] = {"order_id": "1"}
        parsed = _parse_order_time(order)
        assert parsed == datetime.min.replace(tzinfo=timezone.utc)

    def test_parse_order_time_invalid(self) -> None:
        """created_at 无法解析时返回 datetime.min。"""
        order: dict[str, Any] = {"order_id": "1", "created_at": "not-a-date"}
        parsed = _parse_order_time(order)
        assert parsed == datetime.min.replace(tzinfo=timezone.utc)


class TestGetOrderId:
    """_get_order_id 工具函数。"""

    def test_resolved_with_order_id(self) -> None:
        """已解析且有 order_id → 返回 order_id。"""
        result = OrderReferenceResult(resolved=True, order_id=12345)
        ctx = make_context()
        assert _get_order_id(result, ctx) == 12345

    def test_active_reference_fallback(self) -> None:
        """reference_type=active 且上下文有 active_order_id → 返回。"""
        result = OrderReferenceResult(reference_type="active")
        ctx = make_context(active_order_id="98765")
        assert _get_order_id(result, ctx) == 98765

    def test_unresolved_returns_none(self) -> None:
        """未解析 → None。"""
        result = OrderReferenceResult()
        ctx = make_context()
        assert _get_order_id(result, ctx) is None


class TestSummarizeOrders:
    """_summarize_orders 工具函数。"""

    def test_summarize(self) -> None:
        orders = [
            {"order_id": "1", "status": "shipped", "status_label": "已发货", "payable_amount": 100.0},
            {"order_id": "2", "status": "cancelled", "status_label": "已取消", "payable_amount": 50.0},
        ]
        summary = _summarize_orders(orders)
        assert len(summary) == 2
        assert summary[0]["id"] == "1"
        assert summary[1]["status"] == "cancelled"

    def test_empty(self) -> None:
        assert _summarize_orders([]) == []


# ══════════════════════════════════════════════
# 8. OrderReplyBuilder 单元测试
# ══════════════════════════════════════════════


class TestOrderReplyBuilder:
    """OrderReplyBuilder 回复模板。"""

    def _make_order(self, order_id: int, **overrides: Any) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "order_id": str(order_id),
            "status": "shipped",
            "status_label": "已发货",
            "payable_amount": 299.0,
            "items": [
                {"product_name": "无线耳机", "quantity": 1, "subtotal": 299.0},
            ],
        }
        defaults.update(overrides)
        return defaults

    def test_order_list_with_items(self) -> None:
        orders = [self._make_order(101), self._make_order(102, status="cancelled", status_label="已取消")]
        reply = OrderReplyBuilder.order_list(orders, 2)
        assert "订单 #101" in reply
        assert "订单 #102" in reply
        assert "无线耳机" in reply
        assert "299.00" in reply

    def test_order_list_empty(self) -> None:
        reply = OrderReplyBuilder.order_list([], 0)
        assert "暂无" in reply

    def test_order_detail(self) -> None:
        order = self._make_order(101, shipping_address="北京市朝阳区", receiver_phone="13800138000")
        reply = OrderReplyBuilder.order_detail(order)
        assert "订单 #101" in reply
        assert "已发货" in reply
        assert "无线耳机" in reply
        assert "北京市" in reply
        assert "138" in reply

    def test_order_detail_none(self) -> None:
        reply = OrderReplyBuilder.order_detail(None)
        assert "未找到" in reply

    def test_shipping_status_shipped(self) -> None:
        order = self._make_order(101)
        reply = OrderReplyBuilder.shipping_status(order)
        assert "已发货" in reply or "运输" in reply

    def test_shipping_status_cancelled(self) -> None:
        order = self._make_order(101, status="cancelled", status_label="已取消")
        reply = OrderReplyBuilder.shipping_status(order)
        assert "已取消" in reply

    def test_shipping_status_pending(self) -> None:
        order = self._make_order(101, status="pending_customer_confirm", status_label="待确认")
        reply = OrderReplyBuilder.shipping_status(order)
        assert "尚未发货" in reply

    def test_shipping_status_none(self) -> None:
        reply = OrderReplyBuilder.shipping_status(None)
        assert "未找到" in reply

    def test_no_orders(self) -> None:
        reply = OrderReplyBuilder.no_orders()
        assert "暂无" in reply

    def test_clarify_default(self) -> None:
        reply = OrderReplyBuilder.clarify()
        assert "订单信息" in reply

    def test_clarify_custom(self) -> None:
        reply = OrderReplyBuilder.clarify("请提供订单号")
        assert "订单号" in reply
