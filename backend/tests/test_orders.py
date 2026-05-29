"""Phase 10 订单服务层回归测试。

测试覆盖：
  - create_order: 订单创建 + order_items 联写事务
  - get_order: 订单详情查询（含 items）
  - list_orders: 列表 + 筛选 + 分页
  - transition_order_status: 6 步状态机流转
  - cancel_order: 取消订单
  - update_order: 修改订单（增删商品/改地址）
  - tenant 隔离: 跨租户不可见
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.schemas.order import OrderCreate, OrderItemCreate, OrderUpdate
from app.services import order_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_or_create_test_data(db: AsyncSession):
    """获取或创建测试用的 tenant/contact/product（幂等）。"""
    from app.services.contact_service import search_contacts, create_contact
    from app.schemas.contact import ContactCreate

    # 获取第一个已存在的 tenant（如果有的话）
    from sqlalchemy import select, text
    from app.models.tenant import Tenant

    result = await db.execute(select(Tenant).limit(1))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        pytest.skip("数据库无租户，跳过（需先注册一个租户）")
    tenant_id = int(tenant.id)

    # 获取或创建测试联系人
    contacts, _ = await search_contacts(db, tenant_id, limit=1)
    if contacts:
        contact_id = int(contacts[0].id)
    else:
        contact = await create_contact(db, tenant_id, ContactCreate(name="测试客户_订单"))
        contact_id = int(contact.id)

    # 获取或创建测试商品
    from app.models.product import Product

    result = await db.execute(
        select(Product).where(Product.tenant_id == tenant_id).limit(2)
    )
    products = result.scalars().all()
    product_names = [p.name for p in products] if products else ["测试商品A", "测试商品B"]

    return tenant_id, contact_id, product_names


# ---------------------------------------------------------------------------
# Create Order
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_order_basic():
    """创建包含 2 个商品的订单，验证 orders + order_items 联写。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, product_names = await _get_or_create_test_data(db)

        body = OrderCreate(
            contact_id=contact_id,
            items=[
                OrderItemCreate(product_name=product_names[0], quantity=2),
                OrderItemCreate(product_name=product_names[1], quantity=1),
            ],
            receiver_name="张三",
            receiver_phone="13800138000",
            shipping_address="北京市朝阳区测试路 1 号",
            remark="测试订单",
        )

        order = await order_service.create_order(
            db, tenant_id, body, contact_id=contact_id, created_by_type="system"
        )

        assert order.id is not None
        assert order.tenant_id == tenant_id
        assert order.contact_id == contact_id
        assert order.status == "pending_customer_confirm"
        assert order.total_amount > 0
        assert order.payable_amount == order.total_amount
        assert order.discount_amount == 0
        assert order.receiver_name == "张三"
        assert order.receiver_phone == "13800138000"
        assert order.shipping_address == "北京市朝阳区测试路 1 号"
        assert len(order.items) == 2
        assert order.items[0].quantity == 2
        assert order.items[1].quantity == 1
        # product_snapshot 应包含商品名
        assert order.items[0].product_snapshot is not None


@pytest.mark.asyncio
async def test_create_order_without_contact():
    """不指定 contact_id 创建订单。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, product_names = await _get_or_create_test_data(db)

        body = OrderCreate(
            items=[OrderItemCreate(product_name=product_names[0], quantity=1)],
        )

        order = await order_service.create_order(
            db, tenant_id, body, created_by_type="ai"
        )

        assert order.id is not None
        assert order.status == "pending_customer_confirm"
        assert order.created_by_type == "ai"


@pytest.mark.asyncio
async def test_create_order_invalid_product():
    """创建订单时使用不存在的商品名应报错。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, _ = await _get_or_create_test_data(db)

        body = OrderCreate(
            contact_id=contact_id,
            items=[OrderItemCreate(product_name="不存在的商品_XYZ_TEST", quantity=1)],
        )

        with pytest.raises(ValueError) as exc_info:
            await order_service.create_order(
                db, tenant_id, body, contact_id=contact_id,
            )
        assert "不存在" in str(exc_info.value) or "找到" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Get Order
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_order_with_items():
    """查询订单详情应包含 items。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, product_names = await _get_or_create_test_data(db)

        body = OrderCreate(
            contact_id=contact_id,
            items=[OrderItemCreate(product_name=product_names[0], quantity=3)],
        )
        created = await order_service.create_order(db, tenant_id, body)

        order = await order_service.get_order(db, int(created.id), tenant_id)

        assert order is not None
        assert len(order.items) == 1
        assert order.items[0].quantity == 3


@pytest.mark.asyncio
async def test_get_order_wrong_tenant():
    """跨租户查询应返回 None。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, product_names = await _get_or_create_test_data(db)

        body = OrderCreate(
            items=[OrderItemCreate(product_name=product_names[0], quantity=1)],
        )
        created = await order_service.create_order(db, tenant_id, body)

        order = await order_service.get_order(db, int(created.id), 999999)
        assert order is None


# ---------------------------------------------------------------------------
# List Orders
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_orders_pagination():
    """订单列表分页。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, _ = await _get_or_create_test_data(db)

        orders, total = await order_service.list_orders(
            db, tenant_id, page=1, page_size=5
        )
        assert isinstance(orders, list)
        assert isinstance(total, int)


@pytest.mark.asyncio
async def test_list_orders_filter_by_status():
    """按状态筛选订单。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, _ = await _get_or_create_test_data(db)

        orders, total = await order_service.list_orders(
            db, tenant_id, status="cancelled", page=1, page_size=20
        )
        for o in orders:
            assert o.status == "cancelled"


@pytest.mark.asyncio
async def test_list_orders_filter_by_contact():
    """按客户筛选订单。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, _ = await _get_or_create_test_data(db)

        orders, total = await order_service.list_orders(
            db, tenant_id, contact_id=contact_id, page=1, page_size=20
        )
        if orders:
            for o in orders:
                assert o.contact_id == contact_id


# ---------------------------------------------------------------------------
# Status Transitions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transition_pending_to_confirmed():
    """pending_customer_confirm → customer_confirmed。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, product_names = await _get_or_create_test_data(db)

        body = OrderCreate(
            contact_id=contact_id,
            items=[OrderItemCreate(product_name=product_names[0], quantity=1)],
            status="pending_customer_confirm",
        )
        order = await order_service.create_order(db, tenant_id, body)

        updated = await order_service.transition_order_status(
            db, int(order.id), tenant_id, "customer_confirmed"
        )
        assert updated.status == "customer_confirmed"
        assert updated.confirmed_at is not None


@pytest.mark.asyncio
async def test_transition_confirmed_to_agent_confirmed():
    """customer_confirmed → agent_confirmed。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, product_names = await _get_or_create_test_data(db)

        body = OrderCreate(
            contact_id=contact_id,
            items=[OrderItemCreate(product_name=product_names[0], quantity=1)],
            status="customer_confirmed",
        )
        order = await order_service.create_order(db, tenant_id, body)

        updated = await order_service.transition_order_status(
            db, int(order.id), tenant_id, "agent_confirmed"
        )
        assert updated.status == "agent_confirmed"


@pytest.mark.asyncio
async def test_transition_to_shipped():
    """agent_confirmed → shipped。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, product_names = await _get_or_create_test_data(db)

        body = OrderCreate(
            contact_id=contact_id,
            items=[OrderItemCreate(product_name=product_names[0], quantity=1)],
            status="agent_confirmed",
        )
        order = await order_service.create_order(db, tenant_id, body)

        updated = await order_service.transition_order_status(
            db, int(order.id), tenant_id, "shipped"
        )
        assert updated.status == "shipped"
        assert updated.shipped_at is not None


@pytest.mark.asyncio
async def test_transition_shipped_to_signed():
    """shipped → signed。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, product_names = await _get_or_create_test_data(db)

        body = OrderCreate(
            contact_id=contact_id,
            items=[OrderItemCreate(product_name=product_names[0], quantity=1)],
            status="shipped",
        )
        order = await order_service.create_order(db, tenant_id, body)

        updated = await order_service.transition_order_status(
            db, int(order.id), tenant_id, "signed"
        )
        assert updated.status == "signed"
        assert updated.signed_at is not None


@pytest.mark.asyncio
async def test_transition_invalid_should_fail():
    """非法状态流转应报错（signed 是终态）。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, product_names = await _get_or_create_test_data(db)

        body = OrderCreate(
            contact_id=contact_id,
            items=[OrderItemCreate(product_name=product_names[0], quantity=1)],
            status="signed",
        )
        order = await order_service.create_order(db, tenant_id, body)

        with pytest.raises(ValueError) as exc_info:
            await order_service.transition_order_status(
                db, int(order.id), tenant_id, "shipped"
            )
        assert "无法" in str(exc_info.value) or "不允许" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Cancel Order
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_order():
    """取消订单（draft → cancelled）。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, product_names = await _get_or_create_test_data(db)

        body = OrderCreate(
            contact_id=contact_id,
            items=[OrderItemCreate(product_name=product_names[0], quantity=1)],
            status="draft",
        )
        order = await order_service.create_order(db, tenant_id, body)

        ok = await order_service.cancel_order(db, int(order.id), tenant_id)
        assert ok is True

        cancelled = await order_service.get_order(db, int(order.id), tenant_id)
        assert cancelled.status == "cancelled"
        assert cancelled.cancelled_at is not None


# ---------------------------------------------------------------------------
# Update Order
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_order_address():
    """修改订单收货信息。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, product_names = await _get_or_create_test_data(db)

        body = OrderCreate(
            contact_id=contact_id,
            items=[OrderItemCreate(product_name=product_names[0], quantity=1)],
        )
        order = await order_service.create_order(db, tenant_id, body)

        updated = await order_service.update_order(
            db, int(order.id), tenant_id,
            OrderUpdate(
                receiver_name="李四",
                receiver_phone="13900139000",
                shipping_address="上海市浦东新区",
                remark="已更新备注",
            ),
        )
        assert updated.receiver_name == "李四"
        assert updated.receiver_phone == "13900139000"
        assert updated.shipping_address == "上海市浦东新区"
        assert updated.remark == "已更新备注"


# ---------------------------------------------------------------------------
# Batch Status Transition
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_transition():
    """批量状态流转。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, product_names = await _get_or_create_test_data(db)

        ids = []
        for _ in range(2):
            body = OrderCreate(
                contact_id=contact_id,
                items=[OrderItemCreate(product_name=product_names[0], quantity=1)],
                status="customer_confirmed",
            )
            order = await order_service.create_order(db, tenant_id, body)
            ids.append(int(order.id))

        succeeded, failed = await order_service.batch_transition_status(
            db, tenant_id, ids, "agent_confirmed"
        )
        assert len(succeeded) == 2
        assert len(failed) == 0