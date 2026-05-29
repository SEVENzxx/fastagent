"""Phase 10 Agent Skill 回归测试。

测试覆盖：
  - orders.create_order: 真实 orders + order_items 联写事务
  - orders.confirm_order: pending_customer_confirm → customer_confirmed
  - orders.manage_order: 查询订单详情 / 按客户查询最近订单
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.services.ai.agent.skills.orders import (
    create_order,
    confirm_order,
    manage_order,
    _extract_order_id,
    _status_label,
    _build_create_message,
    _order_summary,
    _build_query_result,
    _format_order_message,
)
from app.services.ai.agent.types import ToolResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_test_context(db: AsyncSession):
    """获取测试用 tenant_id / contact_id / product_names。"""
    from sqlalchemy import select
    from app.models.tenant import Tenant

    result = await db.execute(select(Tenant).limit(1))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        pytest.skip("数据库无租户，跳过")
    tenant_id = int(tenant.id)

    # 获取第一个联系人
    from app.models.contact import Contact

    result = await db.execute(
        select(Contact).where(Contact.tenant_id == tenant_id).limit(1)
    )
    contact = result.scalar_one_or_none()
    contact_id = int(contact.id) if contact else None

    # 获取商品名
    from app.models.product import Product

    result = await db.execute(
        select(Product).where(Product.tenant_id == tenant_id).limit(2)
    )
    products = result.scalars().all()
    product_names = [p.name for p in products] if products else ["测试商品A", "测试商品B"]

    return tenant_id, contact_id, product_names


# ---------------------------------------------------------------------------
# ToolResult
# ---------------------------------------------------------------------------

def test_tool_result_ok():
    r = ToolResult(ok=True, skill_name="create_order", result={"order_id": "12345"}, error=None)
    assert r.ok is True
    assert r.skill_name == "create_order"
    assert r.result["order_id"] == "12345"


def test_tool_result_error():
    r = ToolResult(ok=False, skill_name="create_order", error="缺少商品信息")
    assert r.ok is False
    assert r.error == "缺少商品信息"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def test_extract_order_id_from_text():
    assert _extract_order_id("订单号 62712345678901234") is not None
    assert _extract_order_id("订单 123") is None  # 太短
    assert _extract_order_id("no numbers here") is None


def test_status_label_mapping():
    assert _status_label("draft") == "草稿"
    assert _status_label("pending_customer_confirm") == "待客户确认"
    assert _status_label("signed") == "已签收"
    assert _status_label("unknown_status") == "unknown_status"


def test_build_create_message_format():
    items = [
        {"product_name": "龙井茶", "quantity": 2, "unit_price": 128.00, "subtotal": 256.00},
    ]
    msg = _build_create_message(items, 256.00, [])
    assert "龙井茶" in msg
    assert "×2" in msg
    assert "¥256.00" in msg


def test_build_create_message_with_missing():
    items = [{"product_name": "白茶", "quantity": 1, "unit_price": 88.00, "subtotal": 88.00}]
    msg = _build_create_message(items, 88.00, ["address", "phone"])
    assert "请补充" in msg
    assert "收货地址" in msg
    assert "联系电话" in msg


# ---------------------------------------------------------------------------
# Skill: create_order
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_skill_create_order_success():
    """用真实商品名创建订单。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, product_names = await _get_test_context(db)

        result = await create_order(
            tenant_id=tenant_id,
            contact_id=contact_id,
            db=db,
            items=[{"product_name": product_names[0], "quantity": 2}],
            receiver_name="测试收件人",
            receiver_phone="13800000000",
            shipping_address="测试地址",
        )

        assert result.ok is True
        assert result.skill_name == "create_order"
        assert result.result["order_id"] is not None
        assert result.result["status"] == "pending_customer_confirm"
        assert len(result.result["items"]) == 1


@pytest.mark.asyncio
async def test_skill_create_order_no_items():
    """无商品信息时应返回错误。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, _ = await _get_test_context(db)

        result = await create_order(
            tenant_id=tenant_id,
            contact_id=contact_id,
            db=db,
        )
        assert result.ok is False
        assert "商品" in result.error


@pytest.mark.asyncio
async def test_skill_create_order_from_customer_text():
    """从 customer_text 解析商品名。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, product_names = await _get_test_context(db)

        result = await create_order(
            tenant_id=tenant_id,
            contact_id=contact_id,
            db=db,
            customer_text=f"我要下单 {product_names[0]} 3 个",
        )

        assert result.ok is True
        assert result.result["order_id"] is not None


# ---------------------------------------------------------------------------
# Skill: confirm_order
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_skill_confirm_order_success():
    """确认订单 → customer_confirmed。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, product_names = await _get_test_context(db)

        # 先创建订单
        created = await create_order(
            tenant_id=tenant_id,
            contact_id=contact_id,
            db=db,
            items=[{"product_name": product_names[0], "quantity": 1}],
        )
        order_id = int(created.result["order_id"])

        # 确认订单
        result = await confirm_order(
            tenant_id=tenant_id,
            contact_id=contact_id,
            db=db,
            order_id=order_id,
        )

        assert result.ok is True
        assert result.skill_name == "confirm_order"
        assert result.result["status"] == "customer_confirmed"


@pytest.mark.asyncio
async def test_skill_confirm_order_not_found():
    """确认不存在的订单应报错。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, _ = await _get_test_context(db)

        result = await confirm_order(
            tenant_id=tenant_id,
            contact_id=contact_id,
            db=db,
            order_id=99999999999999999,
        )
        assert result.ok is False
        assert "未找到" in result.error


# ---------------------------------------------------------------------------
# Skill: manage_order
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_skill_manage_order_query():
    """查询单个订单。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, product_names = await _get_test_context(db)

        created = await create_order(
            tenant_id=tenant_id,
            contact_id=contact_id,
            db=db,
            items=[{"product_name": product_names[0], "quantity": 2}],
        )
        order_id = int(created.result["order_id"])

        result = await manage_order(
            tenant_id=tenant_id,
            contact_id=contact_id,
            db=db,
            order_id=order_id,
        )

        assert result.ok is True
        assert result.skill_name == "manage_order"
        assert result.result["order_id"] is not None
        assert result.result["status"] is not None


@pytest.mark.asyncio
async def test_skill_manage_order_not_found():
    """查询不存在的订单应报错。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, _ = await _get_test_context(db)

        result = await manage_order(
            tenant_id=tenant_id,
            contact_id=contact_id,
            db=db,
            order_id=99999999999999999,
        )
        assert result.ok is False


@pytest.mark.asyncio
async def test_skill_manage_order_by_contact():
    """按客户查询最近订单。"""
    async with AsyncSessionLocal() as db:
        tenant_id, contact_id, product_names = await _get_test_context(db)

        result = await manage_order(
            tenant_id=tenant_id,
            contact_id=contact_id,
            db=db,
        )

        assert result.ok is True
        assert result.result is not None
        # 可能有关单也可能没有，两种情况都应该正常返回
        if result.result.get("orders") is not None:
            assert isinstance(result.result["orders"], list)
