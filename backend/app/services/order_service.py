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
from app.ai.rag.vector_search import VectorDomain, VectorSearchService

_vector_search = VectorSearchService()


async def list_orders(
    db: AsyncSession,
    tenant_id: int,
    *,
    contact_id: int | None = None,
    status: str | None = None,
    status__in: list[str] | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    employee_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Order], int]:
    """分页查询租户下的订单列表。

    支持按联系人、状态（单值或多值）、创建时间范围、负责坐席多维度过滤。
    所有过滤条件均在 SQL 层面执行，不做内存过滤。

    参数：
        db: 异步数据库会话。
        tenant_id: 租户 ID。
        contact_id: 可选，按联系人过滤。
        status: 可选，按订单状态过滤。
        status__in: 可选，按多个状态过滤（与 status 互斥，同时传入时使用 status__in）。
        created_from: 可选，创建时间起始（含）。
        created_to: 可选，创建时间截止（不含）。
        employee_id: 可选，按负责坐席过滤。
        page: 页码（从 1 开始）。
        page_size: 每页条数。

    返回：
        (订单列表, 总数) 元组。
    """
    conditions = [Order.tenant_id == tenant_id]
    if contact_id is not None:
        conditions.append(Order.contact_id == contact_id)
    if status__in:
        conditions.append(Order.status.in_(status__in))
    elif status is not None:
        conditions.append(Order.status == status)
    if created_from is not None:
        conditions.append(Order.created_at >= created_from)
    if created_to is not None:
        conditions.append(Order.created_at < created_to)
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
    """按 ID 获取租户下单个订单，自动附带联系人名称。

    参数：
        db: 异步数据库会话。
        order_id: 订单 ID。
        tenant_id: 租户 ID。

    返回：
        订单对象，不存在返回 None。
    """
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
    """创建订单，含商品快照生成、总价计算和销售上下文同步。

    SaaS 要点：必须校验 contact 和 product 都属于当前 tenant_id，
    商品不存在时直接拒绝（不采用搜索型接口的宽松策略）。

    参数：
        db: 异步数据库会话。
        tenant_id: 租户 ID。
        body: 订单创建请求体（含 items 和地址/联系方式）。
        contact_id: 备选联系人 ID（body 中未传时使用）。
        conversation_id: 关联会话 ID。
        created_by_type: 创建来源（"agent" / "customer" / "system"）。
        created_by_employee_id: 创建者员工 ID。

    返回：
        新创建的 Order ORM 对象（含 items 关系和联系人名称）。

    异常：
        ValueError: 联系人或商品不存在于当前租户。
    """
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
        if product is None:
            # 下单是有金额、库存和底价约束的业务写操作，不能沿用“搜索不到就保留
            # 用户原文”的宽松策略。否则错误文本会生成 0 元订单，后续库存扣减和
            # 报价审批也失去商品依据。
            raise ValueError(f"未找到可下单商品：{item.product_name}")
        unit_price = product.price if product.price else Decimal("0")
        qty = Decimal(str(item.quantity))
        sub = (unit_price * qty).quantize(Decimal("0.01"))

        snapshot = {
            "product_name": item.product_name,
            "sku": product.sku,
            "specs": product.specs,
            "original_price": float(product.price) if product.price else None,
            "floor_price": float(product.floor_price) if product.floor_price else None,
        }

        item_data.append({
            "product_id": product.id,
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

    # 订单是销售阶段最可靠的业务事实。明细写入后刷新客户画像，
    # 保证工作台无需等待异步任务即可看到最新管线状态。
    await db.flush()
    await db.refresh(order, attribute_names=["items"])
    from app.services.sales_intelligence_service import sync_order_context
    await sync_order_context(db, order)
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
    """更新订单信息，支持增删商品和修改地址/备注等基础字段。

    每次更新后重算 total_amount 和 payable_amount。

    参数：
        db: 异步数据库会话。
        order_id: 订单 ID。
        tenant_id: 租户 ID。
        body: 订单更新请求体。

    返回：
        更新后的订单，不存在返回 None。

    异常：
        ValueError: 新增商品不存在于当前租户。
    """
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
            if product is None:
                raise ValueError(f"未找到可添加商品：{add_item.product_name}")
            unit_price = product.price if product.price else 0
            sub = round(unit_price * add_item.quantity, 2)
            snapshot = {
                "product_name": add_item.product_name,
                "sku": product.sku,
                "original_price": float(product.price) if product.price else None,
            }
            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id,
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
    metadata = dict(order.metadata_ or {})
    metadata["missing_info"] = detect_missing_info_from_order(order)
    order.metadata_ = metadata
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
    """变更订单状态，校验状态流转规则并自动处理库存。

    agent_confirmed 时扣减库存，cancelled 时恢复库存。
    各里程碑状态（confirmed/shipped/signed）自动记录时间戳。

    参数：
        db: 异步数据库会话。
        order_id: 订单 ID。
        tenant_id: 租户 ID。
        to_status: 目标状态。

    返回：
        更新后的订单，不存在返回 None。

    异常：
        ValueError: 状态流转不允许（如从已签收退回）。库存不足。
    """
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

    from app.services.sales_intelligence_service import sync_order_context
    await sync_order_context(db, order)
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
    """批量变更订单状态，逐条处理并收集成功/失败 ID。

    参数：
        db: 异步数据库会话。
        tenant_id: 租户 ID。
        order_ids: 订单 ID 列表。
        to_status: 目标状态。

    返回：
        (成功 ID 列表, 失败 ID 列表) 元组。
    """
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
    """取消订单，内部调用 transition_order_status("cancelled")。

    参数：
        db: 异步数据库会话。
        order_id: 订单 ID。
        tenant_id: 租户 ID。

    返回：
        成功取消返回 True，状态不可变更返回 False。
    """
    try:
        order = await transition_order_status(db, order_id, tenant_id, "cancelled")
        return order is not None
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


async def _match_product(
    db: AsyncSession, tenant_id: int, product_name: str
) -> Product | None:
    """先按精确名称匹配商品，失败后使用 Qdrant 语义召回。"""
    product = await db.scalar(
        select(Product).where(
            Product.tenant_id == tenant_id,
            Product.name == product_name.strip(),
        )
    )
    if product:
        return product

    hits = await _vector_search.search_text(
        domain=VectorDomain.PRODUCT,
        tenant_id=tenant_id,
        query=product_name,
        top_k=1,
        min_score=0.55,
        filters={"is_active": True},
    )
    if not hits:
        return None
    product_id = hits[0].payload.get("product_id")
    if not str(product_id).isdigit():
        return None
    product = await db.scalar(
        select(Product).where(
            Product.tenant_id == tenant_id,
            Product.id == int(product_id),
            Product.is_active.is_(True),
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


def detect_missing_info_from_order(order: Order) -> list[str]:
    """返回订单仍缺失的客户侧必填信息。"""

    missing: list[str] = []
    if not order.shipping_address:
        missing.append("address")
    if not order.receiver_phone:
        missing.append("phone")
    return missing


async def _attach_contact_names(db: AsyncSession, orders: list[Order]) -> None:
    """批量补齐订单列表的联系人名称（_contact_name 属性）。"""
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
