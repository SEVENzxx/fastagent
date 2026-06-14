"""订单类 Skill — Phase 10 真实实现。

create_order: orders + order_items 联写事务
confirm_order: pending_customer_confirm → customer_confirmed
manage_order: 查询订单 / 修改订单
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from app.models.product import Product
from app.schemas.order import OrderCreate as OrderCreateSchema
from app.schemas.order import OrderItemCreate, OrderUpdate
from app.services import order_service
from app.ai.handlers.base import ToolResult
from app.ai.tenant_config import (
    DEFAULT_ORDER_STATUS_LABELS as STATUS_LABELS,
    DEFAULT_FIELD_LABELS as FIELD_LABELS,
    DEFAULT_QUANTITY_UNITS,
)

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

    # 如果 workflow 只传了 query/customer_text，按"一个商品"处理
    if not items_raw:
        customer_text = str(kwargs.get("customer_text") or kwargs.get("query") or "").strip()
        if customer_text:
            items_raw = await _extract_items_from_customer_text(db, tenant_id, customer_text)
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

    return await _create_order_with_status(
        tenant_id=tenant_id,
        contact_id=contact_id,
        db=db,
        order_items=order_items,
        kwargs=kwargs,
        status="pending_customer_confirm",
        skill_name="create_order",
    )


async def create_order_draft(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    db: AsyncSession,
    **kwargs,
) -> ToolResult:
    """创建订单草稿。商品必须已经明确，不能用整句用户话术兜底成商品名。"""
    items_raw = kwargs.get("items") or []
    order_items = []
    for it in items_raw:
        if not isinstance(it, dict):
            continue
        name = str(it.get("product_name") or it.get("name") or "").strip()
        qty = int(it.get("quantity") or 1)
        if name:
            order_items.append(OrderItemCreate(product_name=name, quantity=max(qty, 1)))

    if not order_items:
        return ToolResult(
            ok=False,
            skill_name="create_order_draft",
            error="商品还没有确定，请先让用户选择要购买的具体商品。",
            missing_arguments=["items"],
        )

    return await _create_order_with_status(
        tenant_id=tenant_id,
        contact_id=contact_id,
        db=db,
        order_items=order_items,
        kwargs=kwargs,
        status="draft",
        skill_name="create_order_draft",
    )


async def _create_order_with_status(
    *,
    tenant_id: int,
    contact_id: int | None,
    db: AsyncSession,
    order_items: list[OrderItemCreate],
    kwargs: dict,
    status: str,
    skill_name: str,
) -> ToolResult:
    body = OrderCreateSchema(
        contact_id=contact_id or 0,
        conversation_id=kwargs.get("conversation_id"),
        items=order_items,
        shipping_address=str(kwargs.get("shipping_address") or "").strip() or None,
        receiver_name=str(kwargs.get("receiver_name") or "").strip() or None,
        receiver_phone=str(kwargs.get("receiver_phone") or "").strip() or None,
        remark=str(kwargs.get("remark") or "").strip() or None,
        status=status,
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
        logger.warning("Skill %s 创建失败：%s", skill_name, exc)
        return ToolResult(
            ok=False,
            skill_name=skill_name,
            error=str(exc),
        )

    logger.info(
        "Skill %s 成功：order_id=%s tenant_id=%s contact_id=%s status=%s total=%.2f items=%s",
        skill_name,
        order.id,
        tenant_id,
        contact_id,
        order.status,
        order.payable_amount,
        len(order.items),
    )

    payload = _order_payload(order)
    return ToolResult(
        ok=True,
        skill_name=skill_name,
        result=payload | {"message": _build_create_message(payload["items"], order.payable_amount, payload["missing_info"])},
    )


async def _extract_items_from_customer_text(
    db: AsyncSession,
    tenant_id: int,
    customer_text: str,
) -> list[dict]:
    """从客户原话中提取商品和数量。

    下单属于高风险写操作，不能把整句文本直接交给向量检索后自动选中相似商品。
    这里先读取本租户已启用商品，并采用最长名称优先的包含匹配；这样“茅台”和
    “茅台镇酱香 500ml”同时存在时会命中更具体的商品。没有明确商品名时仍把
    原文保留下来，由订单服务返回“未找到可下单商品”，引导客服确认。
    """
    products = list(
        (
            await db.execute(
                select(Product.name)
                .where(Product.tenant_id == tenant_id, Product.is_active.is_(True))
                .order_by(Product.name)
            )
        ).scalars().all()
    )
    matched_name = next(
        (name for name in sorted(products, key=len, reverse=True) if name and name in customer_text),
        None,
    )
    if matched_name is None:
        return [{"product_name": customer_text, "quantity": 1}]

    tail = customer_text.split(matched_name, 1)[1]
    quantity_match = re.search(rf"(\d+)\s*(?:[{DEFAULT_QUANTITY_UNITS}])?", tail)
    quantity = int(quantity_match.group(1)) if quantity_match else 1
    return [{"product_name": matched_name, "quantity": max(quantity, 1)}]


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

    if order.status == "draft":
        try:
            order = await order_service.transition_order_status(
                db, order_id, tenant_id, "pending_customer_confirm"
            )
        except ValueError as exc:
            return ToolResult(ok=False, skill_name="confirm_order", error=str(exc))

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
        payload = _order_payload(order)
        return ToolResult(
            ok=True,
            skill_name="confirm_order",
            result={
                **payload,
                "message": f"订单 #{order.id} 已确认，等待坐席审核发货。",
            },
        )
    except ValueError as exc:
        return ToolResult(
            ok=False,
            skill_name="confirm_order",
            error=str(exc),
        )


async def cancel_order_draft(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    db: AsyncSession,
    **kwargs,
) -> ToolResult:
    """取消当前订单草稿或待客户确认订单。

    contact_id 校验：contact_id 不为 None 时必须匹配订单所属客户。
    """
    order_id = kwargs.get("order_id")
    if order_id is None:
        return ToolResult(ok=False, skill_name="cancel_order_draft", error="缺少订单号。")
    try:
        order_id = int(order_id)
    except (TypeError, ValueError):
        return ToolResult(ok=False, skill_name="cancel_order_draft", error=f"无效订单号：{order_id}")

    order = await order_service.get_order(db, order_id, tenant_id)
    if order is None:
        return ToolResult(ok=False, skill_name="cancel_order_draft", error=f"未找到订单 #{order_id}。")

    # 取消属于写操作：contact_id 为 None 时拒绝
    if contact_id is None:
        return ToolResult(
            ok=False,
            skill_name="cancel_order_draft",
            error="请先确认客户身份后再取消订单。",
        )

    # 所有权校验：订单必须属于当前客户
    if order.contact_id != contact_id:
        logger.warning(
            "cancel_order_draft 归属校验失败: order=%s tenant=%s order_contact=%s req_contact=%s",
            order_id, tenant_id, order.contact_id, contact_id,
        )
        return ToolResult(ok=False, skill_name="cancel_order_draft", error=f"未找到订单 #{order_id}。")

    if order.status == "cancelled":
        return ToolResult(
            ok=True,
            skill_name="cancel_order_draft",
            result={
                "order_id": str(order.id),
                "status": order.status,
                "status_label": _status_label(order.status),
                "message": "已取消当前订单。如需继续了解商品或重新下单，可以随时告诉我。",
            },
        )

    try:
        order = await order_service.transition_order_status(db, order_id, tenant_id, "cancelled")
    except ValueError as exc:
        return ToolResult(ok=False, skill_name="cancel_order_draft", error=str(exc))

    logger.info(
        "Skill cancel_order_draft 成功：order_id=%s tenant_id=%s new_status=%s",
        order_id,
        tenant_id,
        order.status if order else None,
    )
    return ToolResult(
        ok=True,
        skill_name="cancel_order_draft",
        result={
            "order_id": str(order.id),
            "status": order.status,
            "status_label": _status_label(order.status),
            "message": "已取消当前订单。如需继续了解商品或重新下单，可以随时告诉我。",
        },
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
      - status: str — 单一状态过滤
      - filter_statuses: list[str] — 状态组过滤（转为 SQL status__in）
      - filter_time_ref: str — 时间范围: today / yesterday / this_month / recent（转为 SQL created_from/created_to）
      - page_size: int — 查询条数（默认 5，有过滤条件时自动扩大到 100）
    """
    action = str(kwargs.get("action") or "query").strip().lower()
    order_id = kwargs.get("order_id")
    status = kwargs.get("status")
    filter_statuses = kwargs.get("filter_statuses")
    filter_time_ref = kwargs.get("filter_time_ref")
    page_size = int(kwargs.get("page_size", 5))

    # 有过滤条件时拉取足够数据避免截断
    if filter_statuses or filter_time_ref:
        page_size = max(page_size, 100)

    # 如果没有 order_id，尝试从 customer_text 提取或按客户查询
    if order_id is None:
        raw = str(kwargs.get("customer_text") or kwargs.get("query") or "")
        order_id = _extract_order_id(raw)

    if order_id is not None:
        try:
            order_id = int(order_id)
        except (TypeError, ValueError):
            return ToolResult(ok=False, skill_name="manage_order", error=f"无效订单号: {order_id}")
        # 强制 contact_id：未确认客户身份时不允许按订单号查询
        if contact_id is None:
            return ToolResult(
                ok=False,
                skill_name="manage_order",
                error="请先确认客户身份后查询订单。",
            )
        order = await order_service.get_order(db, order_id, tenant_id)
        if order is None:
            return ToolResult(ok=False, skill_name="manage_order", error=f"未找到订单 #{order_id}。")
        # contact_id 校验：确认订单属于该客户
        if _get_order_contact(order) != contact_id:
            return ToolResult(ok=False, skill_name="manage_order", error=f"未找到订单 #{order_id}。")
        return _build_query_result(order)
    else:
        # 按客户查询最近订单，过滤条件下推到 SQL
        if contact_id is None:
            return ToolResult(
                ok=False,
                skill_name="manage_order",
                error="请提供订单号或确认客户身份。",
            )
        # 将 filter_statuses / filter_time_ref 转为 SQL 条件
        created_from, created_to = _time_ref_to_range(filter_time_ref)
        orders, total = await order_service.list_orders(
            db,
            tenant_id,
            contact_id=contact_id,
            status=str(status) if status and not filter_statuses else None,
            status__in=filter_statuses,
            created_from=created_from,
            created_to=created_to,
            page=1,
            page_size=page_size,
        )
        if not orders:
            return ToolResult(
                ok=True,
                skill_name="manage_order",
                result={
                    "orders": [],
                    "count": 0,
                    "message": "暂无符合条件的订单。",
                },
            )
        order_summaries = [_order_summary(o) for o in orders]
        return ToolResult(
            ok=True,
            skill_name="manage_order",
            result={
                "orders": order_summaries,
                "count": len(order_summaries),
                "message": _format_order_list_message(order_summaries, len(order_summaries)),
            },
        )


async def update_order_draft(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    db: AsyncSession,
    **kwargs,
) -> ToolResult:
    """更新订单草稿：补收货信息、改数量或替换商品后重新返回订单详情。"""
    _ = contact_id
    order_id = kwargs.get("order_id")
    if order_id is None:
        return ToolResult(ok=False, skill_name="update_order_draft", error="缺少订单号。")
    try:
        order_id = int(order_id)
    except (TypeError, ValueError):
        return ToolResult(ok=False, skill_name="update_order_draft", error=f"无效订单号：{order_id}")

    order = await order_service.get_order(db, order_id, tenant_id)
    if order is None:
        return ToolResult(ok=False, skill_name="update_order_draft", error=f"未找到订单 #{order_id}。")
    if order.status not in {"draft", "pending_customer_confirm"}:
        return ToolResult(
            ok=False,
            skill_name="update_order_draft",
            error=f"订单 #{order_id} 当前状态为「{_status_label(order.status)}」，不能由智能客服修改。",
        )

    update = OrderUpdate(
        shipping_address=str(kwargs.get("shipping_address") or "").strip() or None,
        receiver_name=str(kwargs.get("receiver_name") or "").strip() or None,
        receiver_phone=str(kwargs.get("receiver_phone") or "").strip() or None,
        remark=str(kwargs.get("remark") or "").strip() or None,
    )
    if any(
        value is not None
        for value in (update.shipping_address, update.receiver_name, update.receiver_phone, update.remark)
    ):
        order = await order_service.update_order(db, order_id, tenant_id, update)
        if order is None:
            return ToolResult(ok=False, skill_name="update_order_draft", error=f"未找到订单 #{order_id}。")

    product_name = str(kwargs.get("product_name") or "").strip()
    quantity = kwargs.get("quantity")
    if product_name or quantity is not None:
        try:
            order = await _update_first_order_item(
                db,
                tenant_id=tenant_id,
                order=order,
                product_name=product_name or None,
                quantity=int(quantity) if quantity is not None else None,
            )
        except ValueError as exc:
            return ToolResult(ok=False, skill_name="update_order_draft", error=str(exc))

    metadata = dict(order.metadata_ or {})
    metadata["missing_info"] = order_service.detect_missing_info_from_order(order)
    order.metadata_ = metadata
    await db.commit()
    await db.refresh(order)

    payload = _order_payload(order)
    logger.info(
        "Skill update_order_draft 成功：order_id=%s tenant_id=%s missing=%s",
        order.id,
        tenant_id,
        payload["missing_info"],
    )
    return ToolResult(
        ok=True,
        skill_name="update_order_draft",
        result=payload | {"message": _format_order_message(order, payload["items"])},
    )


async def update_draft_order_quantity(
    *,
    tenant_id: int,
    contact_id: int | None = None,
    db: AsyncSession,
    **kwargs,
) -> ToolResult:
    """修改当前订单草稿中的商品数量，并同步重算明细小计和订单金额。"""
    _ = contact_id
    order_id = kwargs.get("order_id")
    if order_id is None:
        return ToolResult(ok=False, skill_name="update_draft_order_quantity", error="缺少订单号。")
    try:
        order_id = int(order_id)
    except (TypeError, ValueError):
        return ToolResult(ok=False, skill_name="update_draft_order_quantity", error=f"无效订单号：{order_id}")

    quantity = kwargs.get("quantity")
    quantity_delta = kwargs.get("quantity_delta")
    if quantity is None and quantity_delta is None:
        return ToolResult(ok=False, skill_name="update_draft_order_quantity", error="请提供要修改的数量。")

    order = await order_service.get_order(db, order_id, tenant_id)
    if order is None:
        return ToolResult(ok=False, skill_name="update_draft_order_quantity", error=f"未找到订单 #{order_id}。")
    if order.status not in {"draft", "pending_customer_confirm"}:
        return ToolResult(
            ok=False,
            skill_name="update_draft_order_quantity",
            error=f"订单 #{order_id} 当前状态为「{_status_label(order.status)}」，不能由智能客服修改数量。",
        )

    product_name = str(kwargs.get("product_name") or "").strip() or None
    item = _find_order_item_for_quantity(order, product_name)
    if item is None:
        return ToolResult(ok=False, skill_name="update_draft_order_quantity", error="订单没有可修改的商品明细。")

    before_quantity = int(item.quantity or 1)
    if quantity_delta is not None:
        after_quantity = max(before_quantity + int(quantity_delta), 1)
    else:
        after_quantity = max(int(quantity), 1)

    item.quantity = after_quantity
    item.subtotal = round(float(item.unit_price) * item.quantity, 2)
    order.total_amount = round(sum(float(it.subtotal) for it in order.items), 2)
    order.payable_amount = round(order.total_amount - float(order.discount_amount), 2)
    metadata = dict(order.metadata_ or {})
    metadata["missing_info"] = order_service.detect_missing_info_from_order(order)
    order.metadata_ = metadata
    await db.commit()
    await db.refresh(order)

    payload = _order_payload(order)
    updated_item = _find_payload_item(payload["items"], item.id)
    logger.info(
        "Skill update_draft_order_quantity 成功：order_id=%s tenant_id=%s before_quantity=%s after_quantity=%s total=%.2f",
        order.id,
        tenant_id,
        before_quantity,
        after_quantity,
        payload["payable_amount"],
    )
    return ToolResult(
        ok=True,
        skill_name="update_draft_order_quantity",
        result=payload | {
            "previous_quantity": before_quantity,
            "new_quantity": after_quantity,
            "message": _build_quantity_update_message(updated_item or payload["items"][0], payload["payable_amount"]),
        },
    )


# ---------------------------------------------------------------------------
# 内部工具方法
# ---------------------------------------------------------------------------

# STATUS_LABELS 和 FIELD_LABELS 已从 tenant_ai_config 导入，支持未来租户级覆盖。


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
        missing_labels = [FIELD_LABELS.get(m, m) for m in missing]
        lines.append(f"请补充：{'、'.join(missing_labels)}")
    return "\n".join(lines)


def _order_summary(order: Order) -> dict:
    items = [
        {
            "product_name": item.product_snapshot.get("product_name") if item.product_snapshot else "",
            "quantity": item.quantity,
            "subtotal": float(item.subtotal),
        }
        for item in (order.items or [])
    ]
    return {
        "order_id": str(order.id),
        "status": order.status,
        "status_label": _status_label(order.status),
        "payable_amount": float(order.payable_amount),
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "items_count": len(items),
        "items": items,
    }


def _format_order_list_message(orders: list[dict], total: int) -> str:
    if not orders:
        return "该客户暂无订单记录。"
    lines = [f"该客户共有 {total} 个订单，以下是最近的 {len(orders)} 个："]
    for index, order in enumerate(orders, start=1):
        lines.append(
            f"{index}. 订单 #{order['order_id']}：{order['status_label']}，"
            f"应付 ¥{order['payable_amount']:.2f}"
        )
        for item in order.get("items") or []:
            name = str(item.get("product_name") or "商品").strip()
            lines.append(f"   - {name} ×{item.get('quantity', 1)}，小计 ¥{float(item.get('subtotal') or 0):.2f}")
    return "\n".join(lines)


def _build_query_result(order: Order) -> ToolResult:
    payload = _order_payload(order)

    return ToolResult(
        ok=True,
        skill_name="manage_order",
        result={
            **payload,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "message": _format_order_message(order, payload["items"]),
        },
    )


async def _update_first_order_item(
    db: AsyncSession,
    *,
    tenant_id: int,
    order: Order,
    product_name: str | None,
    quantity: int | None,
) -> Order:
    item = (order.items or [None])[0]
    if item is None:
        raise ValueError("订单没有商品明细，无法修改。")

    if product_name:
        product = await db.scalar(
            select(Product).where(
                Product.tenant_id == tenant_id,
                Product.is_active.is_(True),
                Product.name == product_name,
            )
        )
        if product is None:
            raise ValueError(f"未找到可替换商品：{product_name}")
        item.product_id = product.id
        item.product_snapshot = {
            "product_name": product.name,
            "sku": product.sku,
            "specs": product.specs,
            "original_price": float(product.price) if product.price else None,
            "floor_price": float(product.floor_price) if product.floor_price else None,
        }
        item.unit_price = product.price if product.price else Decimal("0")

    if quantity is not None:
        item.quantity = max(int(quantity), 1)

    item.subtotal = round(float(item.unit_price) * item.quantity, 2)
    order.total_amount = round(sum(float(it.subtotal) for it in order.items), 2)
    order.payable_amount = round(order.total_amount - float(order.discount_amount), 2)
    return order


def _find_order_item_for_quantity(order: Order, product_name: str | None):
    items = list(order.items or [])
    if not items:
        return None
    if not product_name:
        return items[0]
    return next(
        (
            item for item in items
            if item.product_snapshot
            and str(item.product_snapshot.get("product_name") or "") == product_name
        ),
        items[0],
    )


def _find_payload_item(items: list[dict], item_id: int | None) -> dict | None:
    return next((item for item in items if str(item.get("id")) == str(item_id)), None)


def _order_payload(order: Order) -> dict:
    items = [
        {
            "id": str(item.id),
            "product_id": str(item.product_id) if item.product_id is not None else None,
            "product_name": item.product_snapshot.get("product_name") if item.product_snapshot else "",
            "quantity": item.quantity,
            "unit_price": float(item.unit_price),
            "subtotal": float(item.subtotal),
        }
        for item in (order.items or [])
    ]
    missing = order_service.detect_missing_info_from_order(order)
    return {
        "order_id": str(order.id),
        "status": order.status,
        "status_label": _status_label(order.status),
        "total_amount": float(order.total_amount),
        "payable_amount": float(order.payable_amount),
        "items": items,
        "shipping_address": order.shipping_address,
        "receiver_name": order.receiver_name,
        "receiver_phone": order.receiver_phone,
        "missing_info": missing,
    }


def _build_quantity_update_message(item: dict, payable: float) -> str:
    product_name = str(item.get("product_name") or "商品")
    quantity = int(item.get("quantity") or 1)
    return "\n".join([
        f"已修改数量：已帮您把 {product_name} 修改为 {quantity} 个。",
        f"应付金额：¥{payable:.2f}",
    ])


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


# ── manage_order 过滤辅助函数 ──


def _get_order_contact(order: Order) -> int:
    """从 Order ORM 对象获取 contact_id。"""
    return order.contact_id if order.contact_id is not None else 0


def _time_ref_to_range(
    time_ref: str | None,
) -> tuple[datetime | None, datetime | None]:
    """将 time_ref 转换为 SQL created_from / created_to 条件。

    Returns:
        (created_from, created_to) 元组，两端均为 None 表示无限制。
        created_from 是包含起始，created_to 是不包含截止。
    """
    if time_ref is None:
        return None, None

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if time_ref == "today":
        return today_start, None
    if time_ref == "yesterday":
        yesterday_start = today_start - timedelta(days=1)
        return yesterday_start, today_start
    if time_ref == "this_month":
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return month_start, None
    if time_ref == "recent":
        week_ago = today_start - timedelta(days=7)
        return week_ago, None

    return None, None
