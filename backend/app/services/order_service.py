"""订单管理 service — Phase 10"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.schemas.order import (
    VALID_STATUSES,
    STATUS_TRANSITIONS,
    can_transition,
    OrderCreate,
    OrderUpdate,
)


async def list_orders(
    db: AsyncSession,
    tenant_id: int,
    *,
    contact_id: int | None = None,
    status: str | None = None,
    employee_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Order], int]:
    conditions = [Order.tenant_id == tenant_id]
    if contact_id is not None:
        conditions.append(Order.contact_id == contact_id)
    if status is not None:
        conditions.append(Order.status == status)
    if employee_id is not None:
        conditions.append(Order.employee_id == employee_id)

    base_query = select(Order).where(and_(*conditions))
    total = await db.scalar(select(func.count()).select_from(base_query.subquery()))

    offset = (page - 1) * page_size
    result = await db.execute(
        base_query.order_by(Order.updated_at.desc(), Order.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    orders = list(result.scalars().all())
    await _attach_contact_names(db, orders)
    return orders, total or 0


async def get_order(
    db: AsyncSession, order_id: int, tenant_id: int
) -> Order | None:
    order = await db.scalar(
        select(Order).where(
            Order.id == order_id,
            Order.tenant_id == tenant_id,
        )
    )
    if order is not None:
        await _attach_contact_names(db, [order])
    return order


async def create_order(
    db: AsyncSession,
    tenant_id: int,
    body: OrderCreate,
    *,
    contact_id: int | None = None,
    conversation_id: int | None = None,
    created_by_type: str = "agent",
    created_by_employee_id: int | None = None,
) -> Order:
    effective_contact_id = body.contact_id or contact_id
    if effective_contact_id is None:
        raise ValueError("contact_id 为必填项")

    # 验证联系人在租户内
    contact_exists = await db.scalar(
        select(Contact.id).where(
            Contact.id == effective_contact_id,
            Contact.tenant_id == tenant_id,
        )
    )
    if contact_exists is None:
        raise ValueError("联系人不存在")

    # 解析商品并生成快照
    item_data: list[dict] = []
    total_amount = Decimal("0")

    for item in body.items:
        product = await _match_product(db, tenant_id, item.product_name)
        unit_price = product.price if product and product.price else Decimal("0")
        qty = Decimal(str(item.quantity))
        sub = (unit_price * qty).quantize(Decimal("0.01"))

        snapshot = {
            "product_name": item.product_name,
            "sku": product.sku if product else None,
            "specs": product.specs if product else None,
            "original_price": float(product.price) if product and product.price else None,
            "floor_price": float(product.floor_price) if product and product.floor_price else None,
        }

        item_data.append({
            "product_id": product.id if product else None,
            "product_snapshot": snapshot,
            "quantity": item.quantity,
            "unit_price": float(unit_price),
            "subtotal": float(sub),
        })
        total_amount += sub

    discount = Decimal("0")
    payable = total_amount - discount

    order = Order(
        tenant_id=tenant_id,
        contact_id=effective_contact_id,
        conversation_id=body.conversation_id or conversation_id,
        status=body.status,
        total_amount=float(total_amount),
        discount_amount=float(discount),
        payable_amount=float(payable),
        shipping_address=body.shipping_address,
        receiver_name=body.receiver_name,
        receiver_phone=body.receiver_phone,
        remark=body.remark,
        created_by_type=created_by_type,
        created_by_employee_id=created_by_employee_id,
        metadata_={"missing_info": _detect_missing_info(body)},
    )
    db.add(order)
    await db.flush()

    for item_d in item_data:
        order_item = OrderItem(
            order_id=order.id,
            product_id=item_d["product_id"],
            product_snapshot=item_d["product_snapshot"],
            quantity=item_d["quantity"],
            unit_price=item_d["unit_price"],
            subtotal=item_d["subtotal"],
        )
        db.add(order_item)

    await db.commit()
    await db.refresh(order)
    await _attach_contact_names(db, [order])
    return order


async def update_order(
    db: AsyncSession,
    order_id: int,
    tenant_id: int,
    body: OrderUpdate,
) -> Order | None:
    order = await get_order(db, order_id, tenant_id)
    if order is None:
        return None

    # 基础字段更新
    if body.shipping_address is not None:
        order.shipping_address = body.shipping_address
    if body.receiver_name is not None:
        order.receiver_name = body.receiver_name
    if body.receiver_phone is not None:
        order.receiver_phone = body.receiver_phone
    if body.remark is not None:
        order.remark = body.remark
    if body.discount_amount is not None:
        order.discount_amount = body.discount_amount
        order.payable_amount = round(order.total_amount - body.discount_amount, 2)

    # 新增商品
    if body.add_items:
        for add_item in body.add_items:
            product = await _match_product(db, tenant_id, add_item.product_name)
            unit_price = product.price if product and product.price else 0
            sub = round(unit_price * add_item.quantity, 2)
            snapshot = {
                "product_name": add_item.product_name,
                "sku": product.sku if product else None,
                "original_price": float(product.price) if product and product.price else None,
            }
            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id if product else None,
                product_snapshot=snapshot,
                quantity=add_item.quantity,
                unit_price=unit_price,
                subtotal=sub,
            )
            db.add(order_item)
            order.total_amount = round(order.total_amount + sub, 2)

    # 删除商品
    if body.remove_item_ids:
        for item_id in body.remove_item_ids:
            item = await db.scalar(
                select(OrderItem).where(
                    OrderItem.id == item_id,
                    OrderItem.order_id == order.id,
                )
            )
            if item:
                order.total_amount = round(order.total_amount - item.subtotal, 2)
                await db.delete(item)

    order.payable_amount = round(order.total_amount - order.discount_amount, 2)
    order.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(order)
    await _attach_contact_names(db, [order])
    return order


async def transition_order_status(
    db: AsyncSession,
    order_id: int,
    tenant_id: int,
    to_status: str,
) -> Order | None:
    order = await get_order(db, order_id, tenant_id)
    if order is None:
        return None

    if not can_transition(order.status, to_status):
        allowed = STATUS_TRANSITIONS.get(order.status, set())
        raise ValueError(
            f"不允许从 {order.status} 变更到 {to_status}，"
            f"允许的目标状态: {', '.join(sorted(allowed)) if allowed else '无（终态）'}"
        )

    now = datetime.now(timezone.utc)

    if to_status == "agent_confirmed":
        await _deduct_inventory_for_order(db, order, now)
    elif to_status == "cancelled":
        await _restore_inventory_for_order(db, order, now)

    order.status = to_status
    order.updated_at = now

    if to_status == "customer_confirmed":
        order.confirmed_at = now
    elif to_status == "shipped":
        order.shipped_at = now
    elif to_status == "signed":
        order.signed_at = now
    elif to_status == "cancelled":
        order.cancelled_at = now

    await db.commit()
    await db.refresh(order)
    await _attach_contact_names(db, [order])
    return order


async def batch_transition_status(
    db: AsyncSession,
    tenant_id: int,
    order_ids: list[int],
    to_status: str,
) -> tuple[list[int], list[int]]:
    succeeded: list[int] = []
    failed: list[int] = []

    for oid in order_ids:
        try:
            result = await transition_order_status(db, oid, tenant_id, to_status)
            if result is not None:
                succeeded.append(oid)
            else:
                failed.append(oid)
        except ValueError:
            failed.append(oid)

    return succeeded, failed


async def cancel_order(
    db: AsyncSession,
    order_id: int,
    tenant_id: int,
) -> bool:
    try:
        order = await transition_order_status(db, order_id, tenant_id, "cancelled")
        return order is not None
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _match_product(
    db: AsyncSession, tenant_id: int, product_name: str
) -> Product | None:
    """按商品名精确匹配或 ILIKE 匹配，租户隔离。"""
    product = await db.scalar(
        select(Product).where(
            Product.tenant_id == tenant_id,
            Product.name == product_name.strip(),
        )
    )
    if product:
        return product

    product = await db.scalar(
        select(Product).where(
            Product.tenant_id == tenant_id,
            Product.name.ilike(f"%{product_name.strip()}%"),
        )
    )
    return product


async def _deduct_inventory_for_order(
    db: AsyncSession,
    order: Order,
    now: datetime,
) -> None:
    """订单进入坐席确认态时扣减库存。

    创建订单和客户确认只表示意向，不锁库存；坐席审核通过后才认为订单有效。
    metadata.inventory_deducted 用于避免重复扣减。
    """
    metadata = dict(order.metadata_ or {})
    if metadata.get("inventory_deducted"):
        return

    for item in order.items:
        if item.product_id is None:
            continue
        product = await db.scalar(
            select(Product).where(
                Product.id == item.product_id,
                Product.tenant_id == order.tenant_id,
            ).with_for_update()
        )
        if product is None:
            raise ValueError("订单商品不存在，无法扣减库存")
        if product.stock < item.quantity:
            name = item.product_snapshot.get("product_name") if item.product_snapshot else product.name
            raise ValueError(f"商品库存不足：{name}，当前库存 {product.stock}，需要 {item.quantity}")
        product.stock -= item.quantity

    metadata["inventory_deducted"] = True
    metadata["inventory_deducted_at"] = now.isoformat()
    order.metadata_ = metadata


async def _restore_inventory_for_order(
    db: AsyncSession,
    order: Order,
    now: datetime,
) -> None:
    """取消已扣库存的订单时回补库存。"""
    metadata = dict(order.metadata_ or {})
    if not metadata.get("inventory_deducted"):
        return
    if metadata.get("inventory_restored"):
        return

    for item in order.items:
        if item.product_id is None:
            continue
        product = await db.scalar(
            select(Product).where(
                Product.id == item.product_id,
                Product.tenant_id == order.tenant_id,
            ).with_for_update()
        )
        if product is not None:
            product.stock += item.quantity

    metadata["inventory_restored"] = True
    metadata["inventory_restored_at"] = now.isoformat()
    order.metadata_ = metadata


def _detect_missing_info(body: OrderCreate) -> list[str]:
    missing: list[str] = []
    if not body.shipping_address:
        missing.append("address")
    if not body.receiver_phone:
        missing.append("phone")
    return missing


async def _attach_contact_names(db: AsyncSession, orders: list[Order]) -> None:
    contact_ids = {o.contact_id for o in orders}
    if not contact_ids:
        for o in orders:
            o._contact_name = None
        return

    result = await db.execute(
        select(Contact.id, Contact.name).where(Contact.id.in_(contact_ids))
    )
    name_map = {cid: name for cid, name in result.all()}
    for o in orders:
        o._contact_name = name_map.get(o.contact_id)
