"""OrderReplyBuilder — 订单回复模板集中管理。

不把回复文案散落在 Handler 或 Skill 中。
"""
from __future__ import annotations

from typing import Any


class OrderReplyBuilder:
    """订单回复模板。"""

    @staticmethod
    def order_list(orders: list[dict[str, Any]], count: int) -> str:
        """订单列表回复。

        Args:
            orders: 订单摘要列表 [{"order_id", "status", "status_label", "payable_amount", "items"}]
            count: 总订单数
        """
        if not orders:
            return "该客户暂无订单记录。"

        lines: list[str] = []
        if count > len(orders):
            lines.append(f"该客户共有 {count} 个订单，以下是最近的 {len(orders)} 个：")
        else:
            lines.append(f"该客户共有 {count} 个订单：")

        for index, order in enumerate(orders, start=1):
            oid = order.get("order_id", "")
            status_label = order.get("status_label", order.get("status", ""))
            amount = float(order.get("payable_amount", 0))
            lines.append(f"{index}. 订单 #{oid}：{status_label}，应付 ¥{amount:.2f}")
            for item in order.get("items") or []:
                name = str(item.get("product_name") or "商品").strip()
                qty = item.get("quantity", 1)
                subtotal = float(item.get("subtotal") or 0)
                lines.append(f"   - {name} ×{qty}，小计 ¥{subtotal:.2f}")

        lines.append("")
        lines.append("请回复序号查看详情。")
        return "\n".join(lines)

    @staticmethod
    def order_detail(order: dict[str, Any] | None) -> str:
        """订单详情回复。

        Args:
            order: 订单详情字典，含 order_id / status_label / items / payable_amount 等
        """
        if order is None:
            return "未找到该订单信息。"

        oid = order.get("order_id", "")
        status_label = order.get("status_label", order.get("status", ""))
        items: list[dict[str, Any]] = order.get("items", [])
        payable = float(order.get("payable_amount", 0))

        lines: list[str] = [
            f"订单 #{oid}",
            f"状态：{status_label}",
        ]
        if items:
            lines.append("商品明细：")
            for it in items:
                name = it.get("product_name", "商品")
                qty = it.get("quantity", 1)
                subtotal = float(it.get("subtotal") or 0)
                lines.append(f"  • {name} ×{qty}  ¥{subtotal:.2f}")

        lines.append(f"应付金额：¥{payable:.2f}")

        addr = order.get("shipping_address")
        if addr:
            lines.append(f"收货地址：{addr}")
        phone = order.get("receiver_phone")
        if phone:
            lines.append(f"联系电话：{phone}")

        return "\n".join(lines)

    @staticmethod
    def shipping_status(order: dict[str, Any] | None) -> str:
        """物流状态回复。

        Args:
            order: 订单详情字典
        """
        if order is None:
            return "未找到该订单信息。"

        oid = order.get("order_id", "")
        status_label = order.get("status_label", order.get("status", ""))
        items: list[dict[str, Any]] = order.get("items", [])

        lines: list[str] = [f"订单 #{oid} 当前状态：{status_label}"]
        if items:
            names = [it.get("product_name", "商品") for it in items[:3]]
            lines.append(f"商品：{'、'.join(names)}")

        sl = status_label.lower()
        if "发货" in sl or sl == "shipped":
            lines.append("您的商品已在运输途中，请耐心等待。")
        elif "签收" in sl or sl == "signed":
            lines.append("您的商品已签收，感谢您的购买！")
        elif "取消" in sl or sl == "cancelled":
            lines.append("该订单已取消。")
        else:
            lines.append("该订单尚未发货，请耐心等待。")

        return "\n".join(lines)

    @staticmethod
    def no_orders() -> str:
        """暂无订单提示。"""
        return "该客户暂无订单记录。"

    @staticmethod
    def order_create_pending_exists() -> str:
        """已有下单流程时的提示。"""
        return "您当前已有一个下单流程未完成，请继续按上一步提示补充信息，或回复“取消”后重新下单。"

    @staticmethod
    def order_create_start_in_progress() -> str:
        """下单入口短锁命中时的提示。"""
        return "我已经在处理这笔下单了，请稍等或继续按提示操作。"

    @staticmethod
    def clarify(message: str = "") -> str:
        """追问提示。"""
        return message or "请提供更具体的订单信息，如订单号或订单状态。"
