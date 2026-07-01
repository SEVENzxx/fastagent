"""StatusResolver — 订单状态解析组件。

将用户文本中的状态描述映射到 Order.status 枚举值。

纯规则实现，不调 LLM。
"""

from __future__ import annotations


# Order.status 合法值（参考 order.py）：
# draft / pending_customer_confirm / customer_confirmed / agent_confirmed
# / shipped / signed / cancelled

# 中文状态到单一状态值的映射（精确匹配，不包含"未发货"类宽泛查询）
_STATUS_MAP: dict[str, str] = {
    "待确认": "pending_customer_confirm",
    "待审核": "customer_confirmed",
    "未确认": "pending_customer_confirm",
    "已确认": "customer_confirmed",
    "已审核": "agent_confirmed",
    "已发货": "shipped",
    "配送中": "shipped",
    "运输中": "shipped",
    "已签收": "signed",
    "已完成": "signed",
    "已取消": "cancelled",
    "已退款": "cancelled",
}

# 状态分组（用于范围查询）
_STATUS_GROUPS: dict[str, list[str]] = {
    "unshipped": ["pending_customer_confirm", "customer_confirmed", "agent_confirmed"],
    "active": ["customer_confirmed", "agent_confirmed", "shipped"],
    "finished": ["signed", "cancelled"],
}


class StatusResolver:
    """订单状态映射器。"""

    @staticmethod
    def resolve(text: str) -> str | None:
        """将中文状态文本映射到 Order.status 值。

        Args:
            text: 用户文本，如"未发货"、"已取消"

        Returns:
            映射到的 status 值，无匹配返回 None
        """
        for keyword, status in _STATUS_MAP.items():
            if keyword in text:
                return status
        return None

    @staticmethod
    def resolve_group(text: str) -> list[str] | None:
        """将中文状态文本映射到状态分组。

        Args:
            text: 用户文本，如"未发货"、"进行中"、"已完成"

        Returns:
            该分组覆盖的状态列表，无匹配返回 None
        """
        # 未发货组：已创建但未发货的订单（不含 shipped）
        if any(w in text for w in ("未发货", "待发货", "没发货", "没有发货", "还没发货", "未发")):
            return _STATUS_GROUPS.get("unshipped")
        # 进行中组：已确认到已发货之间（含 shipped）
        if any(w in text for w in ("进行", "处理中", "活跃")):
            return _STATUS_GROUPS.get("active")
        # 已完成组：已签收或已取消
        if any(w in text for w in ("完成", "签收", "结束", "历史")):
            return _STATUS_GROUPS.get("finished")
        return None

    @staticmethod
    def display_name(status: str) -> str:
        """将 Order.status 值转换为中文显示名。

        Args:
            status: Order.status 值

        Returns:
            中文显示名
        """
        display: dict[str, str] = {
            "draft": "草稿",
            "pending_customer_confirm": "待确认",
            "customer_confirmed": "待审核",
            "agent_confirmed": "待发货",
            "shipped": "已发货",
            "signed": "已签收",
            "cancelled": "已取消",
        }
        return display.get(status, status)
