"""销售智能服务 — 客户阶段推进、报价策略、待办/跟进计划、客户 360 视图。"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.employee import Employee
from app.models.order import Order
from app.models.product import Product
from app.models.sales_intelligence import ContactProductContext, ConversationTodo, FollowupPlan, SalesContext
from app.models.sales_memory import SalesMemory
from app.schemas.sales_intelligence import FollowupPlanCreate, TodoCreate, TodoUpdate

# 客户阶段 rank 映射：数字越大越靠后，只允许向前推进（rank 增大）
_STAGE_RANKS = {"new": 0, "inquiry": 1, "negotiation": 2, "ordered": 3, "after_sales": 4, "closed": 5}


async def ensure_sales_context(db: AsyncSession, tenant_id: int, contact_id: int) -> SalesContext:
    """懒初始化客户销售上下文。"""
    context = await db.scalar(
        select(SalesContext).where(SalesContext.tenant_id == tenant_id, SalesContext.contact_id == contact_id)
    )
    if context is None:
        context = SalesContext(tenant_id=tenant_id, contact_id=contact_id)
        db.add(context)
        await db.flush()
    return context


async def advance_contact_stage(db: AsyncSession, tenant_id: int, contact_id: int, stage: str) -> None:
    """推进客户阶段（仅允许向前推进）。"""
    context = await ensure_sales_context(db, tenant_id, contact_id)
    if _STAGE_RANKS.get(stage, 0) >= _STAGE_RANKS.get(context.stage, 0):
        context.stage = stage
    context.last_interaction_at = datetime.now(timezone.utc)


async def sync_order_context(db: AsyncSession, order: Order) -> None:
    """订单创建/变更后同步客户阶段和客户×商品上下文。"""
    # 根据订单状态决定客户整体阶段
    stage = "ordered" if order.status not in {"draft", "cancelled"} else "negotiation"
    await advance_contact_stage(db, order.tenant_id, order.contact_id, stage)

    # 逐商品更新客户×商品上下文
    product_stage = "ordered" if order.status not in {"draft", "cancelled"} else "negotiating"
    for item in order.items:
        if item.product_id is None:
            continue
        item_context = await db.scalar(
            select(ContactProductContext).where(
                ContactProductContext.tenant_id == order.tenant_id,
                ContactProductContext.contact_id == order.contact_id,
                ContactProductContext.product_id == item.product_id,
            )
        )
        if item_context is None:
            item_context = ContactProductContext(
                tenant_id=order.tenant_id,
                contact_id=order.contact_id,
                product_id=item.product_id,
            )
            db.add(item_context)
        item_context.stage = product_stage
        item_context.quoted_price = item.unit_price
        item_context.order_id = order.id


async def update_price_strategy(
    db: AsyncSession,
    tenant_id: int,
    contact_id: int,
    *,
    product_id: int | None = None,
    product_name: str | None = None,
    quoted_price: float,
) -> dict:
    """保存报价并自动分档（正常/折扣/低于底价待审批）。"""
    # 查找商品
    conditions = [Product.tenant_id == tenant_id, Product.is_active.is_(True)]
    if product_id is not None:
        conditions.append(Product.id == product_id)
    elif product_name:
        conditions.append(Product.name == product_name.strip())
    else:
        raise ValueError("请提供商品 ID 或商品名称")
    product = await db.scalar(select(Product).where(*conditions))
    if product is None:
        raise ValueError("商品不存在或已下架")

    # 使用 Decimal 精确计算金额，保留两位小数
    price = Decimal(str(quoted_price)).quantize(Decimal("0.01"))
    standard = Decimal(str(product.price or 0)).quantize(Decimal("0.01"))
    floor = Decimal(str(product.floor_price or product.price or 0)).quantize(Decimal("0.01"))

    # 报价分档判定
    if price < floor:
        price_level, pricing_level, stage = 3, "below_floor_pending", "negotiating"
    elif price < standard:
        price_level, pricing_level, stage = 2, "discount", "quoted"
    else:
        price_level, pricing_level, stage = 1, "normal", "quoted"

    # 更新客户×商品上下文（ContactProductContext）
    context = await db.scalar(
        select(ContactProductContext).where(
            ContactProductContext.tenant_id == tenant_id,
            ContactProductContext.contact_id == contact_id,
            ContactProductContext.product_id == product.id,
        )
    )
    if context is None:
        context = ContactProductContext(tenant_id=tenant_id, contact_id=contact_id, product_id=product.id)
        db.add(context)
    context.stage = stage
    context.quoted_price = price
    context.price_level = price_level

    # 更新客户销售上下文（SalesContext）
    sales_context = await ensure_sales_context(db, tenant_id, contact_id)
    sales_context.stage = "negotiation"
    sales_context.pricing_level = pricing_level
    sales_context.last_interaction_at = datetime.now(timezone.utc)
    await db.commit()
    return {
        "product_id": str(product.id),
        "product_name": product.name,
        "quoted_price": float(price),
        "floor_price": float(floor),
        "price_level": price_level,
        "pricing_level": pricing_level,
        "requires_approval": price_level == 3,
    }


async def list_todos(
    db: AsyncSession,
    tenant_id: int,
    *,
    conversation_id: int | None = None,
    contact_id: int | None = None,
) -> list[ConversationTodo]:
    """查询待办列表。"""
    stmt = select(ConversationTodo).where(ConversationTodo.tenant_id == tenant_id)
    if conversation_id is not None:
        stmt = stmt.where(ConversationTodo.conversation_id == conversation_id)
    if contact_id is not None:
        stmt = stmt.where(ConversationTodo.contact_id == contact_id)
    result = await db.execute(stmt.order_by(
        ConversationTodo.status.asc(),
        ConversationTodo.due_at.asc().nullslast(),
        ConversationTodo.created_at.desc(),
    ))
    return list(result.scalars().all())


async def create_todo(db: AsyncSession, tenant_id: int, body: TodoCreate) -> ConversationTodo:
    """创建待办事项。"""
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == body.conversation_id,
            Conversation.tenant_id == tenant_id,
        )
    )
    if conversation is None:
        raise ValueError("会话不存在")
    todo = ConversationTodo(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        contact_id=conversation.contact_id,
        content=body.content,
        keywords=body.keywords,
        due_at=body.due_at,
        created_by_type=body.created_by_type,
    )
    db.add(todo)
    await db.commit()
    await db.refresh(todo)
    return todo


async def update_todo(db: AsyncSession, tenant_id: int, todo_id: int, body: TodoUpdate) -> ConversationTodo | None:
    """部分更新待办事项。"""
    todo = await db.scalar(
        select(ConversationTodo).where(
            ConversationTodo.id == todo_id,
            ConversationTodo.tenant_id == tenant_id,
        )
    )
    if todo is None:
        return None
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(todo, key, value)
    todo.completed_at = datetime.now(timezone.utc) if todo.status == "done" else None
    await db.commit()
    await db.refresh(todo)
    return todo


async def create_followup(db: AsyncSession, tenant_id: int, body: FollowupPlanCreate) -> FollowupPlan:
    """创建跟进计划，同步更新销售上下文跟进状态为 scheduled。"""
    contact = await db.scalar(
        select(Contact).where(Contact.id == body.contact_id, Contact.tenant_id == tenant_id)
    )
    if contact is None:
        raise ValueError("联系人不存在")
    plan = FollowupPlan(tenant_id=tenant_id, **body.model_dump())
    db.add(plan)

    # 同步更新销售上下文的跟进状态
    context = await ensure_sales_context(db, tenant_id, body.contact_id)
    context.followup_state = "scheduled"
    context.next_followup_at = body.scheduled_at
    await db.commit()
    await db.refresh(plan)
    return plan


async def get_contact_360(db: AsyncSession, tenant_id: int, contact_id: int) -> dict | None:
    """获取客户 360 全景画像（聚合视图）。"""
    contact = await db.scalar(
        select(Contact).where(Contact.id == contact_id, Contact.tenant_id == tenant_id)
    )
    if contact is None:
        return None

    # 懒初始化销售上下文
    context = await ensure_sales_context(db, tenant_id, contact_id)

    # 分配坐席名称
    employee_name = None
    if contact.assigned_employee_id:
        employee_name = await db.scalar(
            select(Employee.display_name).where(Employee.id == contact.assigned_employee_id)
        )

    # 销售记忆（按更新时间倒序）
    memories = list((await db.execute(
        select(SalesMemory).where(
            SalesMemory.tenant_id == tenant_id,
            SalesMemory.contact_id == contact_id,
        ).order_by(SalesMemory.updated_at.desc())
    )).scalars().all())

    # 商品交互上下文（关联商品名称）
    products = list((await db.execute(
        select(ContactProductContext, Product.name)
        .join(Product, Product.id == ContactProductContext.product_id)
        .where(
            ContactProductContext.tenant_id == tenant_id,
            ContactProductContext.contact_id == contact_id,
        )
        .order_by(ContactProductContext.updated_at.desc())
    )).all())

    # 最近 5 笔订单
    orders = list((await db.execute(
        select(Order).where(
            Order.tenant_id == tenant_id,
            Order.contact_id == contact_id,
        ).order_by(Order.created_at.desc()).limit(5)
    )).scalars().all())

    # 待办事项
    todos = await list_todos(db, tenant_id, contact_id=contact_id)

    # 最近 10 条跟进计划
    followups = list((await db.execute(
        select(FollowupPlan).where(
            FollowupPlan.tenant_id == tenant_id,
            FollowupPlan.contact_id == contact_id,
        ).order_by(FollowupPlan.scheduled_at.desc()).limit(10)
    )).scalars().all())

    return {
        "contact_id": contact.id,
        "name": contact.name,
        "phone": contact.phone,
        "address": contact.address,
        "tags": contact.tags or [],
        "assigned_employee_name": employee_name,
        "sales_context": context,
        "memories": memories,
        "product_contexts": [(item, name) for item, name in products],
        "orders": [
            {
                "id": str(order.id),
                "status": order.status,
                "payableAmount": float(order.payable_amount),
                "createdAt": order.created_at.isoformat(),
            }
            for order in orders
        ],
        "todos": todos,
        "followups": followups,
    }
