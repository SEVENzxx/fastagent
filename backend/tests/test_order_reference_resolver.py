"""OrderReferenceResolver 单元测试。

覆盖所有引用类型：
  1. 显式订单号 → resolved
  2. 状态条件 → status 过滤
  3. 时间条件 → time_ref 过滤
  4. 上下文 active_order_id → resolved
  5. "我的订单" → recent 意图，不自动选中
  6. 空文本 → unresolved
"""

from __future__ import annotations

import pytest

from app.ai.components.order_reference import (
    OrderReferenceResolver,
    OrderReferenceResult,
)
from app.ai.context.session_context import SessionContext


def make_context(**overrides: dict) -> SessionContext:
    defaults: dict = {
        "tenant_id": 1,
        "conversation_id": 1,
    }
    defaults.update(overrides)
    return SessionContext(**defaults)


class TestOrderNumber:
    """显式订单号解析。"""

    @pytest.mark.asyncio
    async def test_full_order_number(self) -> None:
        """订单号 20240614001 → resolved=True, order_id=20240614001。"""
        resolver = OrderReferenceResolver()
        ctx = make_context()
        result = await resolver.resolve("订单号 20240614001", contact_id=1, context=ctx)
        assert result.resolved is True
        assert result.order_id == 20240614001
        assert result.order_number == "20240614001"
        assert result.reference_type == "order_number"

    @pytest.mark.asyncio
    async def test_bare_order_number(self) -> None:
        """纯数字订单号也能解析。"""
        resolver = OrderReferenceResolver()
        ctx = make_context()
        result = await resolver.resolve("20240614001", contact_id=1, context=ctx)
        assert result.resolved is True
        assert result.order_id == 20240614001
        assert result.reference_type == "order_number"

    @pytest.mark.asyncio
    async def test_short_number_not_order(self) -> None:
        """7 位以下数字不当作订单号。"""
        resolver = OrderReferenceResolver()
        ctx = make_context()
        result = await resolver.resolve("订单 1234567", contact_id=1, context=ctx)
        assert result.resolved is False
        assert result.reference_type != "order_number"

    @pytest.mark.asyncio
    async def test_order_number_no_space(self) -> None:
        """订单号20240614001（无空格）能解析出 order_number。"""
        resolver = OrderReferenceResolver()
        ctx = make_context()
        result = await resolver.resolve("订单号20240614001", contact_id=1, context=ctx)
        assert result.resolved is True
        assert result.order_id == 20240614001
        assert result.reference_type == "order_number"


class TestStatusFilter:
    """状态条件解析。"""

    @pytest.mark.asyncio
    async def test_unshipped(self) -> None:
        """未发货 → statuses 包含 unshipped 组，不是单一 pending_customer_confirm。"""
        resolver = OrderReferenceResolver()
        ctx = make_context()
        result = await resolver.resolve("未发货的订单", contact_id=1, context=ctx)
        assert result.resolved is False
        assert result.status is None
        assert "pending_customer_confirm" in result.statuses
        assert "customer_confirmed" in result.statuses
        assert "agent_confirmed" in result.statuses
        assert result.reference_type == "status"

    @pytest.mark.asyncio
    async def test_unshipped_group_query(self) -> None:
        """"还没有发货的订单有哪些" → statuses 含 unshipped 组。"""
        resolver = OrderReferenceResolver()
        ctx = make_context()
        result = await resolver.resolve("还没有发货的订单有哪些", contact_id=1, context=ctx)
        assert result.resolved is False
        assert "pending_customer_confirm" in result.statuses
        assert "customer_confirmed" in result.statuses
        assert "agent_confirmed" in result.statuses
        assert "shipped" not in result.statuses
        assert result.reference_type == "status"

    @pytest.mark.asyncio
    async def test_cancelled(self) -> None:
        """已取消 → status=cancelled。"""
        resolver = OrderReferenceResolver()
        ctx = make_context()
        result = await resolver.resolve("已取消的订单", contact_id=1, context=ctx)
        assert result.status == "cancelled"
        assert result.reference_type == "status"

    @pytest.mark.asyncio
    async def test_completed(self) -> None:
        """已完成 → statuses 含 finished 组（signed + cancelled）。"""
        resolver = OrderReferenceResolver()
        ctx = make_context()
        result = await resolver.resolve("已完成订单", contact_id=1, context=ctx)
        assert result.status is None
        assert "signed" in result.statuses
        assert "cancelled" in result.statuses
        assert result.reference_type == "status"


class TestTimeFilter:
    """时间条件解析。"""

    @pytest.mark.asyncio
    async def test_today(self) -> None:
        """今天下单的 → time_ref=today。"""
        resolver = OrderReferenceResolver()
        ctx = make_context()
        result = await resolver.resolve("今天下单的", contact_id=1, context=ctx)
        assert result.resolved is False
        assert result.time_ref == "today"
        assert result.reference_type == "time"

    @pytest.mark.asyncio
    async def test_yesterday(self) -> None:
        """昨天的订单 → time_ref=yesterday。"""
        resolver = OrderReferenceResolver()
        ctx = make_context()
        result = await resolver.resolve("昨天的订单", contact_id=1, context=ctx)
        assert result.time_ref == "yesterday"
        assert result.reference_type == "time"

    @pytest.mark.asyncio
    async def test_this_month(self) -> None:
        """这个月的订单 → time_ref=this_month。"""
        resolver = OrderReferenceResolver()
        ctx = make_context()
        result = await resolver.resolve("这个月的订单", contact_id=1, context=ctx)
        assert result.time_ref == "this_month"


class TestCombinedFilter:
    """组合过滤条件（状态 + 时间）。"""

    @pytest.mark.asyncio
    async def test_unshipped_today(self) -> None:
        """"今天还没发货的订单" → statuses + time_ref=today。"""
        resolver = OrderReferenceResolver()
        ctx = make_context()
        result = await resolver.resolve("今天还没发货的订单", contact_id=1, context=ctx)
        assert result.resolved is False
        assert "pending_customer_confirm" in result.statuses
        assert "customer_confirmed" in result.statuses
        assert "agent_confirmed" in result.statuses
        assert result.time_ref == "today"

    @pytest.mark.asyncio
    async def test_cancelled_yesterday(self) -> None:
        """"昨天已取消的订单" → status=cancelled + time_ref=yesterday。"""
        resolver = OrderReferenceResolver()
        ctx = make_context()
        result = await resolver.resolve("昨天已取消的订单", contact_id=1, context=ctx)
        assert result.resolved is False
        assert result.status == "cancelled"
        assert result.time_ref == "yesterday"


class TestRecentIntent:
    """近期订单意图——不自动选中第一个。"""

    @pytest.mark.asyncio
    async def test_view_my_orders(self) -> None:
        """查看我的订单 → recent，不 resolved。"""
        resolver = OrderReferenceResolver()
        ctx = make_context()
        result = await resolver.resolve("查看我的订单", contact_id=1, context=ctx)
        assert result.resolved is False
        assert result.reference_type == "recent"
        assert result.order_id is None

    @pytest.mark.asyncio
    async def test_recent_orders(self) -> None:
        """最近订单 → time_ref=recent（"最近"被解析为时间条件）。"""
        resolver = OrderReferenceResolver()
        ctx = make_context()
        result = await resolver.resolve("最近订单", contact_id=1, context=ctx)
        assert result.resolved is False
        assert result.time_ref == "recent"
        assert result.reference_type == "time"

    @pytest.mark.asyncio
    async def test_list_all_orders(self) -> None:
        """查订单 → recent。"""
        resolver = OrderReferenceResolver()
        ctx = make_context()
        result = await resolver.resolve("查订单", contact_id=1, context=ctx)
        assert result.resolved is False
        assert result.reference_type == "recent"


class TestActiveContext:
    """上下文 active_order_id。"""

    @pytest.mark.asyncio
    async def test_uses_active_order_id(self) -> None:
        """上下文中 active_order_id + 订单意图 → resolved。"""
        resolver = OrderReferenceResolver()
        ctx = make_context(active_order_id="12345678901")
        result = await resolver.resolve("这个订单怎么样了", contact_id=1, context=ctx)
        assert result.resolved is True
        assert result.order_id == 12345678901
        assert result.reference_type == "active"

    @pytest.mark.asyncio
    async def test_no_order_intent_ignores_context(self) -> None:
        """无订单意图时不使用 active_order_id。"""
        resolver = OrderReferenceResolver()
        ctx = make_context(active_order_id="12345678901")
        result = await resolver.resolve("你好", contact_id=1, context=ctx)
        assert result.resolved is False
        assert result.reference_type == "unresolved"


class TestListIntentWithActive:
    """列表意图不解析 active_order_id。"""

    @pytest.mark.asyncio
    async def test_view_my_orders_with_active(self) -> None:
        """active_order_id 存在时，"查看我的订单" 不能 resolved active。"""
        resolver = OrderReferenceResolver()
        ctx = make_context(active_order_id="20240614001")
        result = await resolver.resolve("查看我的订单", contact_id=1, context=ctx)
        assert result.resolved is False
        assert result.reference_type == "recent"
        assert result.order_id is None

    @pytest.mark.asyncio
    async def test_list_orders_with_active(self) -> None:
        """active_order_id 存在时，"查订单" 不能 resolved active。"""
        resolver = OrderReferenceResolver()
        ctx = make_context(active_order_id="20240614001")
        result = await resolver.resolve("查订单", contact_id=1, context=ctx)
        assert result.resolved is False
        assert result.reference_type == "recent"


class TestShippingEnquiryWithActive:
    """物流查询引用 active_order_id。"""

    @pytest.mark.asyncio
    async def test_shipping_enquiry_with_deixis(self) -> None:
        """"这个什么时候发货" → resolved active。"""
        resolver = OrderReferenceResolver()
        ctx = make_context(active_order_id="20240614001")
        result = await resolver.resolve("这个什么时候发货", contact_id=1, context=ctx)
        assert result.resolved is True
        assert result.order_id == 20240614001
        assert result.reference_type == "active"

    @pytest.mark.asyncio
    async def test_shipping_enquiry_bare(self) -> None:
        """"发货了吗" → resolved active。"""
        resolver = OrderReferenceResolver()
        ctx = make_context(active_order_id="20240614001")
        result = await resolver.resolve("发货了吗", contact_id=1, context=ctx)
        assert result.resolved is True
        assert result.order_id == 20240614001
        assert result.reference_type == "active"

    @pytest.mark.asyncio
    async def test_logistics_enquiry(self) -> None:
        """"物流到哪了" → resolved active。"""
        resolver = OrderReferenceResolver()
        ctx = make_context(active_order_id="20240614001")
        result = await resolver.resolve("物流到哪了", contact_id=1, context=ctx)
        assert result.resolved is True
        assert result.order_id == 20240614001
        assert result.reference_type == "active"


class TestOrdinalReference:
    """序号引用从 recent_orders 解析。"""

    @pytest.mark.asyncio
    async def test_first_order(self) -> None:
        """"第一个订单" → 解析到 recent_orders[0]。"""
        resolver = OrderReferenceResolver()
        ctx = make_context(
            recent_orders=[
                {"id": "11111111111", "status": "pending_customer_confirm"},
                {"id": "22222222222", "status": "shipped"},
            ],
        )
        result = await resolver.resolve("第一个订单", contact_id=1, context=ctx)
        assert result.resolved is True
        assert result.order_id == 11111111111
        assert result.reference_type == "ordinal"

    @pytest.mark.asyncio
    async def test_second_order(self) -> None:
        """"第二个订单" → 解析到 recent_orders[1]。"""
        resolver = OrderReferenceResolver()
        ctx = make_context(
            recent_orders=[
                {"id": "11111111111", "status": "pending_customer_confirm"},
                {"id": "22222222222", "status": "shipped"},
            ],
        )
        result = await resolver.resolve("第二个订单", contact_id=1, context=ctx)
        assert result.resolved is True
        assert result.order_id == 22222222222
        assert result.reference_type == "ordinal"

    @pytest.mark.asyncio
    async def test_ordinal_out_of_range(self) -> None:
        """序号超出 recent_orders 范围 → 不 resolved。"""
        resolver = OrderReferenceResolver()
        ctx = make_context(
            recent_orders=[
                {"id": "11111111111", "status": "pending_customer_confirm"},
            ],
        )
        result = await resolver.resolve("第三个订单", contact_id=1, context=ctx)
        assert result.resolved is False

    @pytest.mark.asyncio
    async def test_ordinal_empty_recent(self) -> None:
        """recent_orders 为空时序号不解析。"""
        resolver = OrderReferenceResolver()
        ctx = make_context()
        result = await resolver.resolve("第一个订单", contact_id=1, context=ctx)
        assert result.resolved is False

    @pytest.mark.asyncio
    async def test_ordinal_bare_first(self) -> None:
        """"第一个"（无"订单"后缀）→ 解析到 recent_orders[0]。"""
        resolver = OrderReferenceResolver()
        ctx = make_context(
            recent_orders=[
                {"id": "11111111111", "status": "pending_customer_confirm"},
                {"id": "22222222222", "status": "shipped"},
            ],
        )
        result = await resolver.resolve("第一个", contact_id=1, context=ctx)
        assert result.resolved is True
        assert result.order_id == 11111111111
        assert result.reference_type == "ordinal"

    @pytest.mark.asyncio
    async def test_ordinal_just_now_prefix(self) -> None:
        """"刚才第一个" → 解析到 recent_orders[0]。"""
        resolver = OrderReferenceResolver()
        ctx = make_context(
            recent_orders=[
                {"id": "11111111111", "status": "pending_customer_confirm"},
                {"id": "22222222222", "status": "shipped"},
            ],
        )
        result = await resolver.resolve("刚才第一个", contact_id=1, context=ctx)
        assert result.resolved is True
        assert result.order_id == 11111111111
        assert result.reference_type == "ordinal"

    @pytest.mark.asyncio
    async def test_ordinal_look_prefix(self) -> None:
        """"看第一个" → 解析到 recent_orders[0]。"""
        resolver = OrderReferenceResolver()
        ctx = make_context(
            recent_orders=[
                {"id": "11111111111", "status": "pending_customer_confirm"},
                {"id": "22222222222", "status": "shipped"},
            ],
        )
        result = await resolver.resolve("看第一个", contact_id=1, context=ctx)
        assert result.resolved is True
        assert result.order_id == 11111111111
        assert result.reference_type == "ordinal"


class TestEdgeCases:
    """边界情况。"""

    @pytest.mark.asyncio
    async def test_empty_text(self) -> None:
        """空文本 → unresolved。"""
        resolver = OrderReferenceResolver()
        ctx = make_context()
        result = await resolver.resolve("", contact_id=1, context=ctx)
        assert result.resolved is False
        assert result.reference_type == "unresolved"

    @pytest.mark.asyncio
    async def test_none_text(self) -> None:
        """None → unresolved。"""
        resolver = OrderReferenceResolver()
        ctx = make_context()
        result = await resolver.resolve(None, contact_id=1, context=ctx)  # type: ignore[arg-type]
        assert result.resolved is False
        assert result.reference_type == "unresolved"

    @pytest.mark.asyncio
    async def test_no_order_related(self) -> None:
        """无订单相关文本 → unresolved。"""
        resolver = OrderReferenceResolver()
        ctx = make_context()
        result = await resolver.resolve("推荐耳机", contact_id=1, context=ctx)
        assert result.resolved is False
        assert result.reference_type == "unresolved"

    @pytest.mark.asyncio
    async def test_order_number_overrides_status(self) -> None:
        """订单号优先级高于状态。"""
        resolver = OrderReferenceResolver()
        ctx = make_context()
        result = await resolver.resolve(
            "订单 20240614001 已取消的", contact_id=1, context=ctx,
        )
        assert result.resolved is True
        assert result.reference_type == "order_number"
        assert result.order_id == 20240614001
