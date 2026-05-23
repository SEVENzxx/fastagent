"""会话与消息服务"""

from datetime import datetime, timezone

from sqlalchemy import and_, func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.employee import Employee
from app.schemas.conversation import ConversationCreate, ConversationUpdate, MessageCreate


async def _get_contact(db: AsyncSession, tenant_id: int, contact_id: int) -> Contact:
    """校验联系人属于当前租户，并返回联系人对象。"""
    contact = await db.scalar(
        select(Contact).where(Contact.id == contact_id, Contact.tenant_id == tenant_id)
    )
    if contact is None:
        raise ValueError("联系人不存在")
    return contact


async def _ensure_employee(db: AsyncSession, tenant_id: int, employee_id: int | None) -> None:
    """校验坐席属于当前租户且未被软删除。

    employee_id 允许为空，表示当前会话暂时进入未分配池。
    """
    if employee_id is None:
        return
    exists = await db.scalar(
        select(Employee.id).where(
            Employee.id == employee_id,
            Employee.tenant_id == tenant_id,
            Employee.deleted_at.is_(None),
        )
    )
    if exists is None:
        raise ValueError("员工不存在")


async def attach_conversation_extras(db: AsyncSession, conversations: list[Conversation]) -> None:
    """给会话列表补充前端展示字段。

    Conversation 表只保存 contact_id / employee_id 等核心外键；列表页还需要客户名、坐席名、
    未读数和最后一条消息预览，所以统一在 service 层批量补齐，避免每个 API 端点重复查询。
    """
    contact_ids = {item.contact_id for item in conversations}
    employee_ids = {item.employee_id for item in conversations if item.employee_id is not None}
    conversation_ids = [item.id for item in conversations]

    contact_map: dict[int, tuple[str, str | None]] = {}
    if contact_ids:
        result = await db.execute(
            select(Contact.id, Contact.name, Contact.avatar_url).where(Contact.id.in_(contact_ids))
        )
        contact_map = {contact_id: (name, avatar_url) for contact_id, name, avatar_url in result.all()}

    employee_map: dict[int, str] = {}
    if employee_ids:
        result = await db.execute(
            select(Employee.id, Employee.display_name, Employee.email).where(Employee.id.in_(employee_ids))
        )
        employee_map = {
            employee_id: display_name or email
            for employee_id, display_name, email in result.all()
        }

    unread_map: dict[int, int] = {}
    preview_map: dict[int, str | None] = {}
    if conversation_ids:
        unread_result = await db.execute(
            select(Message.conversation_id, func.count())
            .where(
                Message.conversation_id.in_(conversation_ids),
                Message.is_read.is_(False),
                Message.sender_type == "CUSTOMER",
            )
            .group_by(Message.conversation_id)
        )
        unread_map = {conversation_id: count for conversation_id, count in unread_result.all()}

        for conversation in conversations:
            latest = await db.scalar(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            preview_map[conversation.id] = latest.content if latest and not latest.is_recalled else None

    for conversation in conversations:
        contact_name, avatar_url = contact_map.get(conversation.contact_id, (None, None))
        conversation._contact_name = contact_name
        conversation._contact_avatar_url = avatar_url
        conversation._employee_name = employee_map.get(conversation.employee_id)
        conversation._unread_count = unread_map.get(conversation.id, 0)
        conversation._last_message_preview = preview_map.get(conversation.id)


async def list_conversations(
    db: AsyncSession,
    tenant_id: int,
    *,
    status: str | None = None,
    keyword: str = "",
    employee_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Conversation], int]:
    """查询会话列表。

    所有查询都强制带 tenant_id，保证租户隔离；keyword 通过联系人表匹配客户名/电话，
    再回到 conversations 表筛选对应会话。
    """
    conditions = [Conversation.tenant_id == tenant_id]
    if status:
        conditions.append(Conversation.status == status)
    if employee_id is not None:
        conditions.append(Conversation.employee_id == employee_id)

    if keyword.strip():
        pattern = f"%{keyword.strip()}%"
        contact_ids_query = select(Contact.id).where(
            Contact.tenant_id == tenant_id,
            or_(Contact.name.ilike(pattern), Contact.phone.ilike(pattern)),
        )
        conditions.append(Conversation.contact_id.in_(contact_ids_query))

    base_query = select(Conversation).where(and_(*conditions))
    total = await db.scalar(select(func.count()).select_from(base_query.subquery()))
    result = await db.execute(
        base_query.order_by(
            Conversation.last_message_at.desc().nullslast(),
            Conversation.created_at.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list(result.scalars().all())
    await attach_conversation_extras(db, items)
    return items, total or 0


async def get_conversation(db: AsyncSession, conversation_id: int, tenant_id: int) -> Conversation | None:
    """按 ID 获取当前租户下的会话。

    找到后会补齐客户、坐席、未读数等展示字段，供详情页和 WebSocket 鉴权复用。
    """
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
        )
    )
    if conversation is not None:
        await attach_conversation_extras(db, [conversation])
    return conversation


async def create_conversation(
    db: AsyncSession,
    tenant_id: int,
    body: ConversationCreate,
) -> Conversation:
    """打开或创建客户会话。

    当前产品规则是“一个联系人在工作台只有一个会话入口”：
    - 已有未关闭会话：直接返回已有会话。
    - 已有关闭会话：按本次选择的坐席/处理方式恢复它，并保留历史消息继续聊。
    - 没有任何会话：创建新会话，坐席默认取联系人 assigned_employee_id。
    """
    contact = await _get_contact(db, tenant_id, body.contact_id)
    existing = await db.scalar(
        select(Conversation)
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.contact_id == body.contact_id,
        )
        .order_by(
            Conversation.last_message_at.desc().nullslast(),
            Conversation.created_at.desc(),
        )
        .limit(1)
    )
    if existing is not None:
        if existing.status == "closed":
            # “打开会话”是明确的恢复动作；与普通状态下拉不同，它允许把 closed 会话接着聊。
            employee_id = body.employee_id if body.employee_id is not None else contact.assigned_employee_id
            await _ensure_employee(db, tenant_id, employee_id)
            existing.employee_id = employee_id
            existing.status = body.status
            existing.handling_type = body.handling_type
            existing.closed_at = None
            existing.last_message_at = datetime.now(timezone.utc)
            if body.platform_id is not None:
                existing.platform_id = body.platform_id
            if body.tags:
                existing.tags = body.tags
            existing.idle_timeout_seconds = body.idle_timeout_seconds
            await db.commit()
            await db.refresh(existing)
        await attach_conversation_extras(db, [existing])
        return existing

    employee_id = body.employee_id if body.employee_id is not None else contact.assigned_employee_id
    await _ensure_employee(db, tenant_id, employee_id)
    now = datetime.now(timezone.utc)
    conversation = Conversation(
        tenant_id=tenant_id,
        contact_id=body.contact_id,
        employee_id=employee_id,
        platform_id=body.platform_id,
        status=body.status,
        handling_type=body.handling_type,
        tags=body.tags,
        last_message_at=now,
        idle_timeout_seconds=body.idle_timeout_seconds,
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    await attach_conversation_extras(db, [conversation])
    return conversation


async def update_conversation(
    db: AsyncSession,
    conversation_id: int,
    tenant_id: int,
    body: ConversationUpdate,
) -> Conversation | None:
    """更新会话管理字段。

    为了避免误操作，已关闭会话不能通过这个通用更新接口重新打开。
    重新接起关闭会话请走 create_conversation/open 语义，让调用方明确选择联系人、坐席和处理方式。
    """
    conversation = await get_conversation(db, conversation_id, tenant_id)
    if conversation is None:
        return None
    data = body.model_dump(exclude_unset=True)
    if (
        conversation.status == "closed"
        and "status" in data
        and data["status"] != "closed"
    ):
        raise ValueError("会话已关闭，不能重新打开")
    if "employee_id" in data:
        await _ensure_employee(db, tenant_id, data["employee_id"])
    if data.get("status") == "closed" and conversation.closed_at is None:
        conversation.closed_at = datetime.now(timezone.utc)
    if "status" in data and data["status"] != "closed":
        conversation.closed_at = None
    for key, value in data.items():
        setattr(conversation, key, value)
    await db.commit()
    await db.refresh(conversation)
    await attach_conversation_extras(db, [conversation])
    return conversation


async def list_messages(
    db: AsyncSession,
    conversation_id: int,
    tenant_id: int,
    *,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[Message], int]:
    """分页获取消息历史。

    这里先确认会话属于当前租户，再查消息表，避免通过 conversation_id 越权读取其他租户消息。
    """
    conversation = await get_conversation(db, conversation_id, tenant_id)
    if conversation is None:
        raise ValueError("会话不存在")
    base_query = select(Message).where(Message.conversation_id == conversation_id)
    total = await db.scalar(select(func.count()).select_from(base_query.subquery()))
    result = await db.execute(
        base_query.order_by(Message.created_at.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars().all()), total or 0


async def create_message(
    db: AsyncSession,
    conversation_id: int,
    tenant_id: int,
    body: MessageCreate,
) -> tuple[Conversation, Message]:
    """写入一条消息，并同步更新会话的最近消息时间。

    坐席首次回复 pending_human 会话时，状态自动推进到 human_processing，
    这样左侧会话列表能反映“人工已经开始处理”。
    """
    conversation = await get_conversation(db, conversation_id, tenant_id)
    if conversation is None:
        raise ValueError("会话不存在")
    if conversation.status == "closed":
        raise ValueError("会话已关闭，不能发送消息")
    message = Message(
        conversation_id=conversation_id,
        sender_type=body.sender_type,
        content_type=body.content_type,
        content=body.content,
        metadata_=body.metadata or {},
        reply_to_id=body.reply_to_id,
        is_read=body.sender_type != "CUSTOMER",
    )
    now = datetime.now(timezone.utc)
    conversation.last_message_at = now
    if body.sender_type == "AGENT" and conversation.status == "pending_human":
        conversation.status = "human_processing"
        conversation.handling_type = "human"
    db.add(message)
    await db.commit()
    await db.refresh(message)
    await db.refresh(conversation)
    return conversation, message


async def recall_message(db: AsyncSession, message_id: int, conversation_id: int, tenant_id: int) -> Message | None:
    """软撤回消息。

    不删除数据库记录，只修改 is_recalled 和展示内容，方便后续审计或会话回放。
    """
    conversation = await get_conversation(db, conversation_id, tenant_id)
    if conversation is None:
        raise ValueError("会话不存在")
    message = await db.scalar(
        select(Message).where(Message.id == message_id, Message.conversation_id == conversation_id)
    )
    if message is None:
        return None
    message.is_recalled = True
    message.content = "消息已撤回"
    await db.commit()
    await db.refresh(message)
    return message


async def mark_messages_read(db: AsyncSession, conversation_id: int, tenant_id: int) -> int:
    """标记会话内客户消息为已读，并返回更新数量。

    采用简单未读模型：客户发来的未读消息进入会话后批量置为已读。
    后续如果需要“每个坐席独立已读位置”，可以扩展 last_read_at 或 read receipts 表。
    """
    conversation = await get_conversation(db, conversation_id, tenant_id)
    if conversation is None:
        raise ValueError("会话不存在")
    result = await db.execute(
        select(Message).where(
            Message.conversation_id == conversation_id,
            Message.sender_type == "CUSTOMER",
            Message.is_read.is_(False),
        )
    )
    messages = list(result.scalars().all())
    for message in messages:
        message.is_read = True
    await db.commit()
    return len(messages)
