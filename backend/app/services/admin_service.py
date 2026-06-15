"""平台 Admin 服务 — 仪表盘、套餐/LLM 配置/租户 CRUD、跨租户业务查询。"""

import logging

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_crypto import encrypt_secret
from app.core.security import hash_password

logger = logging.getLogger(__name__)
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
from app.services.role_service import AGENT_PERMISSION_CODES, PLATFORM_ONLY_PERMISSION_CODES
from app.services.tenant_template import normalize_template_json


async def dashboard(db: AsyncSession) -> dict:
    """获取平台仪表盘核心运营指标。"""
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
    """查询所有套餐（平台级资源，仅超管可管理）。"""
    return list((await db.execute(select(Plan).order_by(Plan.created_at.desc()))).scalars().all())


async def create_plan(db: AsyncSession, body: PlanCreate) -> Plan:
    """创建新套餐。"""
    if await db.scalar(select(Plan.id).where(Plan.name == body.name.strip())):
        raise ValueError("套餐名称已存在")
    item = Plan(**body.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def update_plan(db: AsyncSession, item_id: int, body: PlanUpdate) -> Plan | None:
    """部分更新套餐信息。"""
    item = await db.get(Plan, item_id)
    if item is None:
        return None
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return item


async def list_llm_configs(db: AsyncSession) -> list[LLMConfig]:
    """查询所有 LLM 配置（平台级资源）。"""
    return list((await db.execute(select(LLMConfig).order_by(LLMConfig.created_at.desc()))).scalars().all())


async def create_llm_config(db: AsyncSession, body: LLMConfigCreate) -> LLMConfig:
    """创建 LLM 配置，API Key 入库前加密。"""
    data = body.model_dump(exclude={"api_key"})
    item = LLMConfig(**data, api_key_encrypted=encrypt_secret(body.api_key))
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def update_llm_config(db: AsyncSession, item_id: int, body: LLMConfigUpdate) -> LLMConfig | None:
    """部分更新 LLM 配置，api_key 仅在前端显式传入时重新加密。"""
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
    """查询所有租户（排除软删除），批量加载关联名称避免 N+1。"""
    items = list((await db.execute(
        select(Tenant).where(Tenant.deleted_at.is_(None)).order_by(Tenant.created_at.desc())
    )).scalars().all())
    await _attach_tenant_names(db, items)
    return items


async def create_tenant(db: AsyncSession, body: TenantCreate) -> dict:
    """创建新租户，同时自动生成租户管理员账号和默认角色。"""
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
    """部分更新租户信息。"""
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
    """校验引用的外键存在性。"""
    if plan_id is not None and await db.get(Plan, plan_id) is None:
        raise ValueError("套餐不存在")
    if config_id is not None and await db.get(LLMConfig, config_id) is None:
        raise ValueError("LLM 配置不存在")


async def _attach_tenant_names(db: AsyncSession, items: list[Tenant]) -> None:
    """批量加载 Plan/LLMConfig 名称，挂载为 _plan_name / _selected_llm_config_name。"""
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
        from app.integrations.redis_client import get_redis_client
        redis = get_redis_client()
        await redis.delete(f"fastagent:llm_config:{tenant_id}")
        await redis.aclose()
    except Exception:
        logger.warning("清除租户 LLM 缓存失败: tenant_id=%s", tenant_id)


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
            from app.integrations.redis_client import get_redis_client
            redis = get_redis_client()
            for tid in tenant_ids:
                await redis.delete(f"fastagent:llm_config:{tid}")
            await redis.aclose()
    except Exception:
        logger.warning("清除 LLM 配置缓存失败: llm_config_id=%s", llm_config_id)


async def list_cross_tenant_conversations(
    db: AsyncSession,
    *,
    tenant_id: int | None = None,
    status: str | None = None,
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """平台级跨租户会话列表，支持按租户、状态、关键词（联系人姓名/电话）过滤。"""

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
    """平台级会话消息下钻，按时间正序排列。"""
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
    """平台级跨租户订单列表，支持按租户和订单状态过滤。"""
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
    """平台级跨租户知识库文档列表，支持按租户和文档状态过滤。"""
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
