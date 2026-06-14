"""平台 Admin 服务 — 仪表盘、套餐/LLM 配置/租户 CRUD、跨租户业务查询。

职责
----
本模块提供超级管理员后台的全部业务逻辑：
  - 平台仪表盘（dashboard）：聚合租户数、活跃租户数、套餐数等核心运营指标
  - 套餐管理（CRUD）：平台级套餐资源的增删改查
  - LLM 配置管理（CRUD）：平台级 LLM 供应商配置的增删改查，API Key 入库前加密
  - 租户管理（CRUD）：创建/更新租户，自动生成租户管理员账号和默认角色
  - 跨租户业务查询：会话列表、消息下钻、订单/知识库文档查询

设计要点
--------
- API Key 通过 secret_crypto.encrypt_secret()（Fernet 对称加密）入库，响应只返回 has_api_key 布尔值。
- 租户创建时自动生成租户管理员账号（含邮箱+密码），并初始化"管理员"和"坐席"两个默认角色。
  租户管理员拥有全部业务权限（排除 MANAGE_TENANTS / MANAGE_PLANS 等平台专有权限）。
- 租户创建校验 slug 全局唯一性和关联的 Plan/LLMConfig 外键有效性。
- 跨租户查询使用 JOIN 一次性加载租户名称、联系人名称等关联信息，避免 N+1 查询。
"""

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_crypto import encrypt_secret
from app.core.security import hash_password
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.employee import Employee
from app.models.knowledge_doc import KnowledgeDoc
from app.models.llm_config import LLMConfig
from app.models.order import Order
from app.models.plan import Plan
from app.models.role import EmployeeRole, Permission, PermissionCode, Role, RolePermission
from app.models.tenant import Tenant
from app.schemas.admin import (
    LLMConfigCreate,
    LLMConfigUpdate,
    PlanCreate,
    PlanUpdate,
    TenantCreate,
    TenantUpdate,
)
from app.services.tenant_template import normalize_template_json

# ── 权限码常量 ──────────────────────────────────────────────────────────────
# 坐席角色默认拥有的基础业务权限
AGENT_PERMISSION_CODES = {
    PermissionCode.VIEW_ASSIGNED_CHATS.value,
    PermissionCode.MANAGE_CONVERSATIONS.value,
    PermissionCode.VIEW_CONTACTS.value,
    PermissionCode.VIEW_PRODUCTS.value,
    PermissionCode.VIEW_ORDERS.value,
    PermissionCode.VIEW_KB.value,
    PermissionCode.VIEW_MARKETING.value,
    PermissionCode.VIEW_IMAGES.value,
}

# 平台专有权限（仅超管可分配，租户管理员角色管理中不可见、不可选）
PLATFORM_ONLY_PERMISSION_CODES = {
    PermissionCode.MANAGE_TENANTS.value,
    PermissionCode.MANAGE_PLANS.value,
    PermissionCode.VIEW_AUDIT_LOGS.value,
    PermissionCode.MANAGE_BACKUPS.value,
    PermissionCode.MANAGE_SYSTEM_SETTINGS.value,
    PermissionCode.EXPORT_DATA.value,
}


async def dashboard(db: AsyncSession) -> dict:
    """获取平台仪表盘核心运营指标。

    参数：
        db: 数据库会话

    返回：
        {
            "tenant_count": int,         # 总租户数（排除软删除）
            "active_tenant_count": int,  # 活跃租户数（is_active=True）
            "plan_count": int,           # 套餐总数
            "llm_config_count": int,     # LLM 配置总数
            "conversation_count": int,   # 平台总会话数
            "order_count": int,          # 平台总订单数
        }

    说明：
        聚合查询涉及 6 张表，用于平台管理后台首页概览卡片展示。
    """
    async def count(model, *conditions) -> int:
        return int(await db.scalar(select(func.count(model.id)).where(*conditions)) or 0)
    return {
        "tenant_count": await count(Tenant, Tenant.deleted_at.is_(None)),
        "active_tenant_count": await count(Tenant, Tenant.deleted_at.is_(None), Tenant.is_active.is_(True)),
        "plan_count": await count(Plan),
        "llm_config_count": await count(LLMConfig),
        "conversation_count": await count(Conversation),
        "order_count": await count(Order),
    }


async def list_plans(db: AsyncSession) -> list[Plan]:
    """查询所有套餐（平台级资源，仅超管可管理）。

    参数：
        db: 数据库会话

    返回：
        按创建时间倒序排列的 Plan 列表
    """
    return list((await db.execute(select(Plan).order_by(Plan.created_at.desc()))).scalars().all())


async def create_plan(db: AsyncSession, body: PlanCreate) -> Plan:
    """创建新套餐。

    参数：
        db: 数据库会话
        body: 套餐创建请求体，包含 name（名称）、limits（限额配置 JSON）、price 等

    返回：
        创建的 Plan ORM 对象

    异常：
        ValueError: 套餐名称已存在（name 全局唯一）
    """
    if await db.scalar(select(Plan.id).where(Plan.name == body.name.strip())):
        raise ValueError("套餐名称已存在")
    item = Plan(**body.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def update_plan(db: AsyncSession, item_id: int, body: PlanUpdate) -> Plan | None:
    """部分更新套餐信息。

    参数：
        db: 数据库会话
        item_id: 套餐 ID
        body: 套餐更新请求体（所有字段可选）

    返回：
        更新后的 Plan ORM 对象，若不存在则返回 None
    """
    item = await db.get(Plan, item_id)
    if item is None:
        return None
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return item


async def list_llm_configs(db: AsyncSession) -> list[LLMConfig]:
    """查询所有 LLM 配置（平台级资源）。

    参数：
        db: 数据库会话

    返回：
        按创建时间倒序排列的 LLMConfig 列表
        注意：响应中不含明文 API Key，仅通过 has_api_key 字段告知是否已配置
    """
    return list((await db.execute(select(LLMConfig).order_by(LLMConfig.created_at.desc()))).scalars().all())


async def create_llm_config(db: AsyncSession, body: LLMConfigCreate) -> LLMConfig:
    """创建 LLM 配置，API Key 入库前加密。

    参数：
        db: 数据库会话
        body: LLM 配置创建请求体，包含 provider、model、api_base、api_key、pricing 等

    返回：
        创建的 LLMConfig ORM 对象

    安全机制：
        API Key 通过 Fernet 对称加密后存入 api_key_encrypted 字段，
        之后通过列表接口查询时只返回 has_api_key=True，不回传密文或明文。
    """
    data = body.model_dump(exclude={"api_key"})
    item = LLMConfig(**data, api_key_encrypted=encrypt_secret(body.api_key))
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def update_llm_config(db: AsyncSession, item_id: int, body: LLMConfigUpdate) -> LLMConfig | None:
    """部分更新 LLM 配置，api_key 仅在前端显式传入时重新加密。

    参数：
        db: 数据库会话
        item_id: LLM 配置 ID
        body: LLM 配置更新请求体（所有字段可选）

    返回：
        更新后的 LLMConfig ORM 对象，若不存在则返回 None

    注意：
        api_key 仅在 body.api_key 不为 None 时才更新（空字符串不会触发更新），
        这样前端可以不传 api_key 字段来保持原有密钥不变。
    """
    item = await db.get(LLMConfig, item_id)
    if item is None:
        return None
    data = body.model_dump(exclude_unset=True, exclude={"api_key"})
    for key, value in data.items():
        setattr(item, key, value)
    if body.api_key is not None:
        item.api_key_encrypted = encrypt_secret(body.api_key)
    await db.commit()
    await db.refresh(item)

    # 清除使用该 LLM 配置的所有租户的 Redis 缓存
    await _invalidate_llm_config_cache(db, item_id)

    return item


async def list_tenants(db: AsyncSession) -> list[Tenant]:
    """查询所有租户（排除软删除），批量加载关联名称避免 N+1。

    参数：
        db: 数据库会话

    返回：
        按创建时间倒序排列的 Tenant 列表，每个租户附加 _plan_name 和 _selected_llm_config_name 属性
    """
    items = list((await db.execute(
        select(Tenant).where(Tenant.deleted_at.is_(None)).order_by(Tenant.created_at.desc())
    )).scalars().all())
    await _attach_tenant_names(db, items)
    return items


async def create_tenant(db: AsyncSession, body: TenantCreate) -> dict:
    """创建新租户，同时自动生成租户管理员账号和默认角色。

    在一个事务中完成以下操作：
        1. 创建 Tenant 记录（校验 slug 唯一性和外键有效性）
        2. 创建租户管理员 Employee（is_superuser=False）
        3. 初始化"管理员"角色（含全部业务权限，排除平台专有权限）
        4. 初始化"坐席"角色（含基础业务权限）
        5. 将管理员员工关联到管理员角色

    参数：
        db: 数据库会话
        body: 租户创建请求体，包含 name、slug、admin_email、admin_password 等

    返回：
        {
            "tenant": Tenant,      # 创建的租户 ORM 对象
            "admin_email": str,     # 管理员邮箱
            "admin_password": str,  # 管理员密码（明文，前端展示给超管）
        }

    校验：
        1. slug 全局唯一
        2. admin_email 全局唯一（不与其他员工冲突）
        3. plan_id / selected_llm_config_id 引用的外键存在

    异常：
        ValueError: slug 已存在、邮箱已存在、外键引用无效
    """
    # 校验唯一性
    if await db.scalar(select(Tenant.id).where(Tenant.slug == body.slug.strip())):
        raise ValueError("企业标识已存在")
    if await db.scalar(select(Employee.id).where(Employee.email == body.admin_email.strip())):
        raise ValueError("管理员邮箱已被使用")
    await _validate_refs(db, body.plan_id, body.selected_llm_config_id)

    # 1. 创建租户
    tenant_data = body.model_dump(exclude={"admin_email", "admin_password", "admin_display_name"})
    if "template_json" in tenant_data:
        tenant_data["template_json"] = normalize_template_json(tenant_data["template_json"], strict=True)
    tenant = Tenant(**tenant_data)
    db.add(tenant)
    await db.flush()

    # 2. 创建租户管理员员工
    admin_employee = Employee(
        tenant_id=tenant.id,
        email=body.admin_email.strip(),
        hashed_password=hash_password(body.admin_password),
        display_name=body.admin_display_name or body.admin_email.split("@")[0],
        is_superuser=False,  # 租户管理员不是平台超管
    )
    db.add(admin_employee)
    await db.flush()

    # 3. 加载全部系统权限码
    permissions = list((await db.execute(select(Permission))).scalars().all())

    # 4. 创建"管理员"角色（租户级全部业务权限，排除平台专有权限）
    admin_role = Role(
        tenant_id=tenant.id,
        name="管理员",
        description="租户管理员，拥有该租户的全部业务权限",
    )
    # 5. 创建"坐席"角色（基础业务权限）
    agent_role = Role(
        tenant_id=tenant.id,
        name="坐席",
        description="默认坐席角色，拥有基础业务权限",
    )
    db.add_all([admin_role, agent_role])
    await db.flush()

    # 6. 分配权限
    for permission in permissions:
        # 管理员角色：全部业务权限（排除平台专有权限）
        if permission.code not in PLATFORM_ONLY_PERMISSION_CODES:
            db.add(RolePermission(role_id=admin_role.id, permission_id=permission.id))
        # 坐席角色：基础业务权限
        if permission.code in AGENT_PERMISSION_CODES:
            db.add(RolePermission(role_id=agent_role.id, permission_id=permission.id))

    # 7. 将管理员员工关联到管理员角色
    db.add(EmployeeRole(employee_id=admin_employee.id, role_id=admin_role.id))

    await db.commit()
    await db.refresh(tenant)
    await _attach_tenant_names(db, [tenant])

    return {
        "tenant": tenant,
        "admin_email": body.admin_email.strip(),
        "admin_password": body.admin_password,
    }


async def update_tenant(db: AsyncSession, item_id: int, body: TenantUpdate) -> Tenant | None:
    """部分更新租户信息。

    参数：
        db: 数据库会话
        item_id: 租户 ID
        body: 租户更新请求体（所有字段可选）

    返回：
        更新后的 Tenant ORM 对象，若不存在或已软删除则返回 None

    校验：
        若传入了 plan_id 或 selected_llm_config_id，校验引用的外键存在

    异常：
        ValueError: 引用的套餐或 LLM 配置不存在
    """
    item = await db.scalar(
        select(Tenant).where(Tenant.id == item_id, Tenant.deleted_at.is_(None))
    )
    if item is None:
        return None
    data = body.model_dump(exclude_unset=True)
    if "template_json" in data:
        data["template_json"] = normalize_template_json(data["template_json"], strict=True)
    await _validate_refs(db, data.get("plan_id"), data.get("selected_llm_config_id"))
    for key, value in data.items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    await _attach_tenant_names(db, [item])

    # selected_llm_config_id 变更 → 清除该租户的 LLM 配置缓存
    if "selected_llm_config_id" in data:
        await _invalidate_tenant_llm_cache(item_id)

    return item


async def _validate_refs(db: AsyncSession, plan_id: int | None, config_id: int | None) -> None:
    """校验引用的外键存在性。

    参数：
        db: 数据库会话
        plan_id: 套餐 ID（None 表示不校验）
        config_id: LLM 配置 ID（None 表示不校验）

    异常：
        ValueError: 引用的套餐或 LLM 配置不存在

    说明：
        私有辅助函数，仅在本模块内部使用。
        在创建/更新租户时统一校验外键引用，避免数据库层面的外键约束报错。
    """
    if plan_id is not None and await db.get(Plan, plan_id) is None:
        raise ValueError("套餐不存在")
    if config_id is not None and await db.get(LLMConfig, config_id) is None:
        raise ValueError("LLM 配置不存在")


async def _attach_tenant_names(db: AsyncSession, items: list[Tenant]) -> None:
    """批量加载 Plan/LLMConfig 名称，挂载为 _plan_name / _selected_llm_config_name。

    参数：
        db: 数据库会话
        items: 需要附加关联名称的 Tenant 列表

    说明：
        私有辅助函数。使用 IN 查询一次性加载所有关联的 Plan 和 LLMConfig 名称，
        挂载为私有属性，避免在模板渲染或序列化时触发 N+1 查询和 DetachedInstanceError。
    """
    plan_ids = {item.plan_id for item in items if item.plan_id is not None}
    config_ids = {item.selected_llm_config_id for item in items if item.selected_llm_config_id is not None}
    plans = dict((await db.execute(
        select(Plan.id, Plan.name).where(Plan.id.in_(plan_ids))
    )).all()) if plan_ids else {}
    configs = dict((await db.execute(
        select(LLMConfig.id, LLMConfig.name).where(LLMConfig.id.in_(config_ids))
    )).all()) if config_ids else {}
    for item in items:
        item._plan_name = plans.get(item.plan_id)
        item._selected_llm_config_name = configs.get(item.selected_llm_config_id)


async def _invalidate_tenant_llm_cache(tenant_id: int) -> None:
    """清除指定租户的 LLM 配置 Redis 缓存。"""
    try:
        from app.redis_client import get_redis_client
        redis = get_redis_client()
        await redis.delete(f"fastagent:llm_config:{tenant_id}")
        await redis.aclose()
    except Exception:
        pass


async def _invalidate_llm_config_cache(db: AsyncSession, llm_config_id: int) -> None:
    """清除所有使用该 LLM 配置的租户的 Redis 缓存。"""
    try:
        tenant_ids = (await db.execute(
            select(Tenant.id).where(
                Tenant.selected_llm_config_id == llm_config_id,
                Tenant.deleted_at.is_(None),
            )
        )).scalars().all()
        if tenant_ids:
            from app.redis_client import get_redis_client
            redis = get_redis_client()
            for tid in tenant_ids:
                await redis.delete(f"fastagent:llm_config:{tid}")
            await redis.aclose()
    except Exception:
        pass


async def list_cross_tenant_conversations(
    db: AsyncSession,
    *,
    tenant_id: int | None = None,
    status: str | None = None,
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """平台级跨租户会话列表，支持按租户、状态、关键词（联系人姓名/电话）过滤。

    参数：
        db: 数据库会话
        tenant_id: 可选，按租户过滤
        status: 可选，按会话状态过滤
        keyword: 可选，按联系人姓名或电话模糊搜索
        page: 页码
        page_size: 每页条数

    返回：
        (会话摘要列表, 总数) 元组。每条摘要包含：
        id, tenant_id, tenant_name, contact_name, employee_name, status,
        handling_type, is_transferred, last_message_at, last_message_preview, created_at

    性能说明：
        使用 JOIN 一次性加载 Tenant.name + Contact.name + Employee.display_name，
        避免 N+1 查询。最新消息预览（last_message_preview）通过子查询获取。
    """
    conditions = []
    if tenant_id is not None:
        conditions.append(Conversation.tenant_id == tenant_id)
    if status:
        conditions.append(Conversation.status == status)
    if keyword.strip():
        pattern = f"%{keyword.strip()}%"
        conditions.append(or_(Contact.name.ilike(pattern), Contact.phone.ilike(pattern)))
    where = and_(*conditions) if conditions else True

    # 计数查询
    count_stmt = (
        select(func.count(Conversation.id))
        .join(Tenant, Tenant.id == Conversation.tenant_id)
        .join(Contact, Contact.id == Conversation.contact_id)
        .where(where)
    )
    total = int(await db.scalar(count_stmt) or 0)

    # 主查询：一次性 JOIN 租户、联系人、坐席
    stmt = (
        select(Conversation, Tenant.name, Contact.name, Employee.display_name, Employee.email)
        .join(Tenant, Tenant.id == Conversation.tenant_id)
        .join(Contact, Contact.id == Conversation.contact_id)
        .outerjoin(Employee, Employee.id == Conversation.employee_id)
        .where(where)
        .order_by(Conversation.last_message_at.desc().nullslast(), Conversation.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).all()
    items: list[dict] = []
    for conversation, tenant_name, contact_name, employee_name, employee_email in rows:
        # 获取最新一条消息内容作为预览
        latest = await db.scalar(
            select(Message.content)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        items.append({
            "id": conversation.id,
            "tenant_id": conversation.tenant_id,
            "tenant_name": tenant_name,
            "contact_name": contact_name,
            "employee_name": employee_name or employee_email,
            "status": conversation.status,
            "handling_type": conversation.handling_type,
            "is_transferred": conversation.is_transferred,
            "last_message_at": conversation.last_message_at,
            "last_message_preview": latest,
            "created_at": conversation.created_at,
        })
    return items, total


async def list_cross_tenant_messages(
    db: AsyncSession, conversation_id: int, *, page: int = 1, page_size: int = 50
) -> tuple[list[Message], int]:
    """平台级会话消息下钻，按时间正序排列。

    参数：
        db: 数据库会话
        conversation_id: 会话 ID
        page: 页码
        page_size: 每页条数

    返回：
        (消息列表, 总数) 元组。会话不存在时返回空列表。
        消息按 created_at 升序排列（对话时间线顺序）。
    """
    if await db.get(Conversation, conversation_id) is None:
        return [], 0
    base = select(Message).where(Message.conversation_id == conversation_id)
    total = int(await db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = await db.execute(
        base.order_by(Message.created_at.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows.scalars().all()), total


async def list_cross_tenant_orders(
    db: AsyncSession,
    *,
    tenant_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """平台级跨租户订单列表，支持按租户和订单状态过滤。

    参数：
        db: 数据库会话
        tenant_id: 可选，按租户过滤
        status: 可选，按订单状态过滤
        page: 页码
        page_size: 每页条数

    返回：
        (订单摘要列表, 总数) 元组。每条摘要包含：
        id, tenant_id, tenant_name, contact_name, status, payable_amount,
        created_by_type, created_at, updated_at
    """
    conditions = []
    if tenant_id is not None:
        conditions.append(Order.tenant_id == tenant_id)
    if status:
        conditions.append(Order.status == status)
    where = and_(*conditions) if conditions else True
    total = int(await db.scalar(select(func.count(Order.id)).where(where)) or 0)
    rows = await db.execute(
        select(Order, Tenant.name, Contact.name)
        .join(Tenant, Tenant.id == Order.tenant_id)
        .join(Contact, Contact.id == Order.contact_id)
        .where(where)
        .order_by(Order.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return [
        {
            "id": order.id,
            "tenant_id": order.tenant_id,
            "tenant_name": tenant_name,
            "contact_name": contact_name,
            "status": order.status,
            "payable_amount": float(order.payable_amount),
            "created_by_type": order.created_by_type,
            "created_at": order.created_at,
            "updated_at": order.updated_at,
        }
        for order, tenant_name, contact_name in rows.all()
    ], total


async def list_cross_tenant_knowledge_docs(
    db: AsyncSession,
    *,
    tenant_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """平台级跨租户知识库文档列表，支持按租户和文档状态过滤。

    参数：
        db: 数据库会话
        tenant_id: 可选，按租户过滤
        status: 可选，按文档处理状态过滤（pending/processing/completed/failed）
        page: 页码
        page_size: 每页条数

    返回：
        (文档摘要列表, 总数) 元组。每条摘要包含：
        id, tenant_id, tenant_name, title, file_type, status, chunk_count,
        error_message, created_at, updated_at
    """
    conditions = []
    if tenant_id is not None:
        conditions.append(KnowledgeDoc.tenant_id == tenant_id)
    if status:
        conditions.append(KnowledgeDoc.status == status)
    where = and_(*conditions) if conditions else True
    total = int(await db.scalar(select(func.count(KnowledgeDoc.id)).where(where)) or 0)
    rows = await db.execute(
        select(KnowledgeDoc, Tenant.name)
        .join(Tenant, Tenant.id == KnowledgeDoc.tenant_id)
        .where(where)
        .order_by(KnowledgeDoc.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return [
        {
            "id": doc.id,
            "tenant_id": doc.tenant_id,
            "tenant_name": tenant_name,
            "title": doc.title,
            "file_type": doc.file_type,
            "status": doc.status,
            "chunk_count": doc.chunk_count,
            "error_message": doc.error_message,
            "created_at": doc.created_at,
            "updated_at": doc.updated_at,
        }
        for doc, tenant_name in rows.all()
    ], total
