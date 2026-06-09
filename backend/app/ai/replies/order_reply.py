"""订单相关确定性回复渲染。"""

from __future__ import annotations


def empty_order_message() -> str:
    return "暂时没有查到相关订单。您可以提供订单号或下单手机号，我再帮您确认。"


def render_order_list(orders: list[dict], total: int) -> str:
    lines = [f"您共有 {total} 个订单，最近 {len(orders)} 个是："]
    for index, order in enumerate(orders[:5], start=1):
        order_id = str(order.get("order_id") or "").strip()
        status = str(order.get("status_label") or order.get("status") or "").strip()
        amount = float(order.get("payable_amount") or 0)
        lines.append(f"{index}. 订单 #{order_id}：{status}，应付 ¥{amount:.2f}")
        items = order.get("items")
        if isinstance(items, list):
            for item in items[:3]:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("product_name") or "商品").strip()
                quantity = item.get("quantity") or 1
                subtotal = float(item.get("subtotal") or 0)
                lines.append(f"   - {name} ×{quantity}，小计 ¥{subtotal:.2f}")
    lines.append("如果您想查看某一单的详细收货信息或物流，请把订单号发给我。")
    return "\n".join(lines)
