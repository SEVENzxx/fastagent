"""StatusResolver 单元测试。

覆盖：
  1. 中文状态 → Order.status 映射
  2. 状态分组解析
  3. display_name 反向映射
  4. 无匹配 → None
"""

from __future__ import annotations

from app.ai.components.status_resolver import StatusResolver


class TestStatusResolver:
    """StatusResolver 映射测试。"""

    def test_unshipped_as_group(self) -> None:
        """"未发货"不再映射单一状态，应使用 resolve_group。"""
        statuses = StatusResolver.resolve_group("未发货")
        assert statuses is not None
        assert "pending_customer_confirm" in statuses
        assert "customer_confirmed" in statuses
        assert "agent_confirmed" in statuses
        assert "shipped" not in statuses

    def test_unshipped_single_no_match(self) -> None:
        """"未发货"从 _STATUS_MAP 移除后 resolve 返回 None。"""
        assert StatusResolver.resolve("未发货") is None
        assert StatusResolver.resolve("待发货") is None

    def test_cancelled(self) -> None:
        assert StatusResolver.resolve("已取消") == "cancelled"

    def test_shipped(self) -> None:
        assert StatusResolver.resolve("已发货") == "shipped"

    def test_signed(self) -> None:
        assert StatusResolver.resolve("已签收") == "signed"
        assert StatusResolver.resolve("已完成") == "signed"

    def test_pending_confirm(self) -> None:
        assert StatusResolver.resolve("待确认") == "pending_customer_confirm"
        assert StatusResolver.resolve("未确认") == "pending_customer_confirm"

    def test_confirmed(self) -> None:
        assert StatusResolver.resolve("已确认") == "customer_confirmed"
        assert StatusResolver.resolve("待审核") == "customer_confirmed"

    def test_no_match(self) -> None:
        assert StatusResolver.resolve("随便看看") is None
        assert StatusResolver.resolve("") is None

    def test_substring_match(self) -> None:
        """关键词在句子中也能匹配。"""
        assert StatusResolver.resolve("那些已取消的订单") == "cancelled"


class TestStatusGroup:
    """状态分组测试。"""

    def test_unshipped_group(self) -> None:
        """"还没发货" → unshipped 组，不含 shipped。"""
        groups = StatusResolver.resolve_group("还没有发货的订单")
        assert groups is not None
        assert "pending_customer_confirm" in groups
        assert "customer_confirmed" in groups
        assert "agent_confirmed" in groups
        assert "shipped" not in groups
        assert "signed" not in groups
        assert "cancelled" not in groups

    def test_unshipped_aliases(self) -> None:
        """"待发货/没发货/未发" → unshipped 组。"""
        for text in ("待发货的", "没发货", "未发的订单"):
            groups = StatusResolver.resolve_group(text)
            assert groups is not None, f"{text} 应解析到 unshipped 组"
            assert "pending_customer_confirm" in groups
            assert "shipped" not in groups

    def test_active_group(self) -> None:
        groups = StatusResolver.resolve_group("进行中的订单")
        assert groups is not None
        assert "customer_confirmed" in groups
        assert "shipped" in groups

    def test_finished_group(self) -> None:
        groups = StatusResolver.resolve_group("已完成订单")
        assert groups is not None
        assert "signed" in groups
        assert "cancelled" in groups

    def test_no_group_match(self) -> None:
        assert StatusResolver.resolve_group("") is None
        assert StatusResolver.resolve_group("hello") is None


class TestDisplayName:
    """display_name 反向映射。"""

    def test_draft(self) -> None:
        assert StatusResolver.display_name("draft") == "草稿"

    def test_shipped(self) -> None:
        assert StatusResolver.display_name("shipped") == "已发货"

    def test_cancelled(self) -> None:
        assert StatusResolver.display_name("cancelled") == "已取消"

    def test_customer_confirmed(self) -> None:
        assert StatusResolver.display_name("customer_confirmed") == "待审核"

    def test_unknown(self) -> None:
        assert StatusResolver.display_name("unknown_status") == "unknown_status"
