"""订单类 Skill — Phase 10 真实实现。

create_order: orders + order_items 联写事务
confirm_order: pending_customer_confirm → customer_confirmed
manage_order: 查询订单 / 修改订单
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from app.schemas.order import OrderCreate as OrderCreateSchema
from app.schemas.order import OrderItemCreate, OrderUpdate
from app.services import order_service
from app.services.ai.agent.types import ToolResult

logger = logging.getLogger(__name__)


async def create_order(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    db: AsyncSession,
    **kwargs,
) -> ToolResult:
    """创建订单 — 真实 orders + order_items 事务写入。

    kwargs 中可传入:
      - items: list[dict] 每项含 product_name / quantity
      - shipping_address / receiver_name / receiver_phone / remark
      - customer_text: str 客户原文（解析地址/电话等）
    """
    items_raw = kwargs.get("items") or []
    if isinstance(items_raw, str):
        import json
        try:
            items_raw = json.loads(items_raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Skill create_order items 解析失败: %s", items_raw)
            items_raw = []

    # 如果 agent 只传了 query/customer_text，按"一个商品"处理
    if not items_raw:
        customer_text = str(kwargs.get("customer_text") or kwargs.get("query") or "").strip()
        if customer_text:
            items_raw = [{"product_name": customer_text, "quantity": 1}]
        else:
            return ToolResult(
                ok=False,
                skill_name="create_order",
                error="缺少商品信息，请告知需要下单的商品名称和数量。",
            )

    order_items = []
    for it in items_raw:
        if isinstance(it, dict):
            name = str(it.get("product_name") or it.get("name") or "").strip()
            qty = int(it.get("quantity") or 1)
        elif isinstance(it, str):
            name = it.strip()
            qty = 1
        else:
            continue
        if name:
            order_items.append(OrderItemCreate(product_name=name, quantity=qty))

    if not order_items:
        return ToolResult(
            ok=False,
            skill_name="create_order",
            error="无法识别商品信息，请告知商品名称。",
        )

    body = OrderCreateSchema(
        contact_id=contact_id or 0,
        items=order_items,
        shipping_address=str(kwargs.get("shipping_address") or "").strip() or None,
        receiver_name=str(kwargs.get("receiver_name") or "").strip() or None,
        receiver_phone=str(kwargs.get("receiver_phone") or "").strip() or None,
        remark=str(kwargs.get("remark") or "").strip() or None,
        status="pending_customer_confirm",
    )

    try:
        order = await order_service.create_order(
            db,
            tenant_id,
            body,
            contact_id=contact_id,
            created_by_type="ai",
        )
    except ValueError as exc:
        logger.warning("Skill create_order 创建失败：%s", exc)
        return ToolResult(
            ok=False,
            skill_name="create_order",
            error=str(exc),
        )

    items_display = [
        {
            "id": str(item.id),
            "product_name": item.product_snapshot.get("product_name") if item.product_snapshot else "",
            "quantity": item.quantity,
            "unit_price": float(item.unit_price),
            "subtotal": float(item.subtotal),
        }
        for item in order.items
    ]

    missing = order.metadata_.get("missing_info", []) if order.metadata_ else []

    logger.info(
        "Skill create_order 成功：order_id=%s tenant_id=%s contact_id=%s status=%s total=%.2f items=%s",
        order.id,
        tenant_id,
        contact_id,
        order.status,
        order.payable_amount,
        len(order.items),
    )

    return ToolResult(
        ok=True,
        skill_name="create_order",
        result={
            "order_id": str(order.id),
            "status": order.status,
            "status_label": _status_label(order.status),
            "total_amount": float(order.total_amount),
            "payable_amount": float(order.payable_amount),
            "items": items_display,
            "shipping_address": order.shipping_address,
            "missing_info": missing,
            "message": _build_create_message(items_display, order.payable_amount, missing),
        },
    )


async def confirm_order(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    db: AsyncSession,
    **kwargs,
) -> ToolResult:
    """确认订单 — pending_customer_confirm → customer_confirmed。

    kwargs 中可传入:
      - order_id: int
      - customer_text: str（尝试从中提取订单号）
    """
    order_id = kwargs.get("order_id")
    if order_id is None:
        raw = str(kwargs.get("customer_text") or kwargs.get("query") or "")
        order_id = _extract_order_id(raw)
        if order_id is None:
            return ToolResult(
                ok=False,
                skill_name="confirm_order",
                error="请提供要确认的订单号。",
            )

    try:
        order_id = int(order_id)
    except (TypeError, ValueError):
        return ToolResult(
            ok=False,
            skill_name="confirm_order",
            error=f"无效的订单号: {order_id}",
        )

    order = await order_service.get_order(db, order_id, tenant_id)
    if order is None:
        return ToolResult(
            ok=False,
            skill_name="confirm_order",
            error=f"未找到订单 #{order_id}。",
        )

    if order.status != "pending_customer_confirm":
        return ToolResult(
            ok=False,
            skill_name="confirm_order",
            error=f"订单 #{order_id} 当前状态为「{_status_label(order.status)}」，无法确认。仅待客户确认的订单可以执行此操作。",
        )

    try:
        order = await order_service.transition_order_status(
            db, order_id, tenant_id, "customer_confirmed"
        )
        logger.info(
            "Skill confirm_order 成功：order_id=%s tenant_id=%s new_status=%s",
            order_id,
            tenant_id,
            order.status,
        )
        return ToolResult(
            ok=True,
            skill_name="confirm_order",
            result={
                "order_id": str(order.id),
                "status": order.status,
                "status_label": _status_label(order.status),
                "message": f"订单 #{order.id} 已确认，等待坐席审核发货。",
            },
        )
    except ValueError as exc:
        return ToolResult(
            ok=False,
            skill_name="confirm_order",
            error=str(exc),
        )


async def manage_order(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    db: AsyncSession,
    **kwargs,
) -> ToolResult:
    """订单管理 — 查询订单状态或修改订单。

    kwargs 中可传入:
      - action: str — "query"（默认）/ "update_address" / "add_note"
      - order_id: int
      - customer_text: str
    """
    action = str(kwargs.get("action") or "query").strip().lower()
    order_id = kwargs.get("order_id")

    # 如果没有 order_id，尝试从 customer_text 提取或按客户查询
    if order_id is None:
        raw = str(kwargs.get("customer_text") or kwargs.get("query") or "")
        order_id = _extract_order_id(raw)

    if order_id is not None:
        try:
            order_id = int(order_id)
        except (TypeError, ValueError):
            return ToolResult(ok=False, skill_name="manage_order", error=f"无效订单号: {order_id}")
        order = await order_service.get_order(db, order_id, tenant_id)
        if order is None:
            return ToolResult(ok=False, skill_name="manage_order", error=f"未找到订单 #{order_id}。")
        return _build_query_result(order)
    else:
        # 按客户查询最近订单
        if contact_id is None:
            return ToolResult(
                ok=False,
                skill_name="manage_order",
                error="请提供订单号或确认客户身份。",
            )
        orders, total = await order_service.list_orders(
            db, tenant_id, contact_id=contact_id, page=1, page_size=5
        )
        if not orders:
            return ToolResult(
                ok=True,
                skill_name="manage_order",
                result={
                    "orders": [],
                    "count": 0,
                    "message": f"该客户暂无订单记录。",
                },
            )
        return ToolResult(
            ok=True,
            skill_name="manage_order",
            result={
                "orders": [_order_summary(o) for o in orders],
                "count": total,
                "message": f"该客户共有 {total} 个订单，以下是最近的 {len(orders)} 个。",
            },
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

STATUS_LABELS = {
    "draft": "草稿",
    "pending_customer_confirm": "待客户确认",
    "customer_confirmed": "客户已确认",
    "agent_confirmed": "坐席已确认",
    "shipped": "已发货",
    "signed": "已签收",
    "cancelled": "已取消",
}


def _status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def _extract_order_id(text: str) -> int | None:
    """从文本中提取订单号（数字串）。"""
    import re
    matches = re.findall(r"\b(\d{15,20})\b", text)
    if matches:
        return int(matches[0])
    return None


def _build_create_message(
    items: list[dict],
    payable: float,
    missing: list[str],
) -> str:
    lines = ["已为您创建订单："]
    for it in items:
        lines.append(
            f"  • {it['product_name']} ×{it['quantity']}  "
            f"单价 ¥{it['unit_price']:.2f}  小计 ¥{it['subtotal']:.2f}"
        )
    lines.append(f"应付金额：¥{payable:.2f}")
    if missing:
        labels = {"address": "收货地址", "phone": "联系电话"}
        missing_labels = [labels.get(m, m) for m in missing]
        lines.append(f"请补充：{'、'.join(missing_labels)}")
    return "\n".join(lines)


def _order_summary(order: Order) -> dict:
    return {
        "order_id": str(order.id),
        "status": order.status,
        "status_label": _status_label(order.status),
        "payable_amount": float(order.payable_amount),
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "items_count": len(order.items) if order.items else 0,
    }


def _build_query_result(order: Order) -> ToolResult:
    items = [
        {
            "id": str(item.id),
            "product_name": item.product_snapshot.get("product_name") if item.product_snapshot else "",
            "quantity": item.quantity,
            "unit_price": float(item.unit_price),
            "subtotal": float(item.subtotal),
        }
        for item in (order.items or [])
    ]

    return ToolResult(
        ok=True,
        skill_name="manage_order",
        result={
            "order_id": str(order.id),
            "status": order.status,
            "status_label": _status_label(order.status),
            "total_amount": float(order.total_amount),
            "payable_amount": float(order.payable_amount),
            "items": items,
            "shipping_address": order.shipping_address,
            "receiver_name": order.receiver_name,
            "receiver_phone": order.receiver_phone,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "message": _format_order_message(order, items),
        },
    )


def _format_order_message(order: Order, items: list[dict]) -> str:
    lines = [
        f"订单 #{order.id}",
        f"状态：{_status_label(order.status)}",
    ]
    if items:
        lines.append("商品明细：")
        for it in items:
            lines.append(f"  • {it['product_name']} ×{it['quantity']}  ¥{it['subtotal']:.2f}")
    lines.append(f"应付金额：¥{order.payable_amount:.2f}")
    if order.shipping_address:
        lines.append(f"收货地址：{order.shipping_address}")
    if order.receiver_phone:
        lines.append(f"联系电话：{order.receiver_phone}")
    return "\n".join(lines)
