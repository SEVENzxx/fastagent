"""销售智能服务 — 客户阶段推进、报价策略、待办/跟进计划、客户 360 视图。

职责
----
本模块提供面向销售场景的智能辅助功能：
  - 客户阶段推进（advance_contact_stage）：单向推进客户阶段（new→inquiry→negotiation→ordered→after_sales→closed）
  - 报价策略（update_price_strategy）：根据商品底价/标准价自动分档，低于底价标记待审批
  - 订单同步（sync_order_context）：订单创建/变更后自动更新客户阶段和商品上下文
  - 待办管理（CRUD）：与聊天会话关联的待办事项，支持状态管理和自动完成时间记录
  - 跟进计划（create_followup）：为联系人制定下次跟进计划，同步更新销售上下文
  - 客户 360（get_contact_360）：聚合 7 表数据，一次性返回客户全景画像

设计要点
--------
- 阶段 rank 只允许向前推进，防止客户阶段回退（如从 "ordered" 退回 "negotiation"）
- 报价低于底价时 automatic requires_approval=True，防止 AI 绕过底价规则
- 所有金额使用 Decimal 精确计算，保留两位小数
- sync_order_context 与 order_service 解耦：订单服务在创建/更新订单后调用本函数同步销售上下文
- get_contact_360 涉及 7 表查询，仅在客户详情页使用，不在列表页频繁调用
"""

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
    """懒初始化客户销售上下文。

    参数：
        db: 数据库会话
        tenant_id: 租户 ID
        contact_id: 联系人 ID

    返回：
        已存在的 SalesContext 或新创建的 SalesContext ORM 对象

    说明：
        该方法在每次需要访问销售上下文时调用，确保即使之前未初始化也能正常运行。
        通过 db.flush() 而非 commit() 来生成 ID，允许在外部事务中统一提交。
    """
    context = await db.scalar(
        select(SalesContext).where(SalesContext.tenant_id == tenant_id, SalesContext.contact_id == contact_id)
    )
    if context is None:
        context = SalesContext(tenant_id=tenant_id, contact_id=contact_id)
        db.add(context)
        await db.flush()
    return context


async def advance_contact_stage(db: AsyncSession, tenant_id: int, contact_id: int, stage: str) -> None:
    """推进客户阶段（仅允许向前推进）。

    参数：
        db: 数据库会话
        tenant_id: 租户 ID
        contact_id: 联系人 ID
        stage: 目标阶段，如 "inquiry"、"negotiation"、"ordered" 等

    阶段流转规则：
        new(0) → inquiry(1) → negotiation(2) → ordered(3) → after_sales(4) → closed(5)
        仅当目标阶段 rank >= 当前阶段 rank 时才更新，防止阶段倒退。
        同时更新 last_interaction_at 为当前 UTC 时间。
    """
    context = await ensure_sales_context(db, tenant_id, contact_id)
    if _STAGE_RANKS.get(stage, 0) >= _STAGE_RANKS.get(context.stage, 0):
        context.stage = stage
    context.last_interaction_at = datetime.now(timezone.utc)


async def sync_order_context(db: AsyncSession, order: Order) -> None:
    """订单创建/变更后同步客户阶段和客户×商品上下文。

    参数：
        db: 数据库会话
        order: 已创建的 Order ORM 对象（需包含 items 关系）

    同步内容：
        1. 客户阶段：根据订单状态决定客户整体阶段（ordered / negotiation）
        2. 客户×商品上下文（ContactProductContext）：逐商品更新
           - 商品交互阶段（ordered / negotiating）
           - 已报价金额（quoted_price）
           - 关联订单 ID

    调用时机：
        在 order_service 创建或更新订单后调用，确保销售管线数据与订单数据一致。
        取消/草稿状态的订单不会将客户阶段推进到 ordered。
    """
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
    """保存报价并自动分档（正常/折扣/低于底价待审批）。

    参数：
        db: 数据库会话
        tenant_id: 租户 ID
        contact_id: 联系人 ID
        product_id: 商品 ID（与 product_name 二选一）
        product_name: 商品名称（与 product_id 二选一）
        quoted_price: 报价金额（float 类型，内部转为 Decimal 精确计算）

    返回：
        {
            "product_id": str,         # 商品 ID
            "product_name": str,       # 商品名称
            "quoted_price": float,     # 报价金额
            "floor_price": float,      # 商品底价
            "price_level": int,        # 报价级别: 1=正常报价, 2=折扣, 3=低于底价
            "pricing_level": str,      # 定价层级: "normal" / "discount" / "below_floor_pending"
            "requires_approval": bool, # 是否需要人工审批（price_level==3 时为 True）
        }

    报价分档规则：
        - price >= standard（标准价）           → price_level=1, "normal"（正常报价）
        - floor <= price < standard             → price_level=2, "discount"（折扣报价）
        - price < floor（底价）                  → price_level=3, "below_floor_pending"（低于底价待审批）

    异常：
        ValueError: 商品不存在或已下架，或未提供商品 ID/名称
    """
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
    """查询待办列表，按状态升序、到期升序（无截止排最后）、创建降序排列。

    参数：
        db: 数据库会话
        tenant_id: 租户 ID
        conversation_id: 可选，按关联会话过滤
        contact_id: 可选，按关联联系人过滤

    返回：
        排序后的 ConversationTodo 列表
    """
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
    """创建待办事项。

    参数：
        db: 数据库会话
        tenant_id: 租户 ID
        body: 待办创建请求体，包含 conversation_id、content、keywords、due_at、created_by_type

    返回：
        创建的 ConversationTodo ORM 对象

    业务逻辑：
        待办自动从关联会话继承 contact_id，确保待办与客户关联。
        通常由客服在与客户对话中手动创建，用于标记需后续跟进的事项。

    异常：
        ValueError: 关联的会话不存在或不属于当前租户
    """
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
    """部分更新待办事项。

    参数：
        db: 数据库会话
        tenant_id: 租户 ID
        todo_id: 待办 ID
        body: 待办更新请求体（所有字段可选）

    返回：
        更新后的 ConversationTodo，若不存在或不属于该租户则返回 None

    自动行为：
        - status='done' 时自动记录完成时间（completed_at）
        - status 改为其他值时自动清除完成时间
    """
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
    """创建跟进计划，同步更新销售上下文跟进状态为 scheduled。

    参数：
        db: 数据库会话
        tenant_id: 租户 ID
        body: 跟进计划创建请求体，包含 contact_id、content、scheduled_at 等

    返回：
        创建的 FollowupPlan ORM 对象

    业务逻辑：
        1. 验证联系人存在且属于当前租户
        2. 创建跟进计划记录
        3. 同步更新销售上下文（SalesContext）的跟进状态和时间

    异常：
        ValueError: 联系人不存在或不属于当前租户
    """
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
    """获取客户 360 全景画像（聚合视图）。

    参数：
        db: 数据库会话
        tenant_id: 租户 ID
        contact_id: 联系人 ID

    返回：
        None（联系人不存在）或包含以下字段的字典：
        {
            "contact_id": int,              # 联系人 ID
            "name": str,                    # 姓名
            "phone": str,                   # 电话
            "address": str,                 # 地址
            "tags": list[str],              # 标签列表
            "assigned_employee_name": str,  # 分配的坐席名称
            "sales_context": SalesContext,  # 销售上下文（阶段/意向/预算等）
            "memories": list[SalesMemory],  # 销售记忆列表
            "product_contexts": list[(ContactProductContext, product_name)],  # 商品交互上下文
            "orders": list[dict],           # 最近 5 笔订单摘要
            "todos": list[ConversationTodo],# 待办事项列表
            "followups": list[FollowupPlan],# 最近 10 条跟进计划
        }

    性能注意：
        涉及 7 张表的跨表聚合查询（Contact + SalesContext + Employee + SalesMemory
        + ContactProductContext + Product + Order + ConversationTodo + FollowupPlan）。
        仅在客户详情页（右侧画像面板）调用，勿在列表页频繁使用。
    """
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

    await db.commit()
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
