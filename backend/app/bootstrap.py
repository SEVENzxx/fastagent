"""平台基础数据初始化 — 权限码 / 默认租户 / 超管账号 / 系统设置 / 意图样本。

使用方式:
    cd backend
    uv run python -m app.bootstrap

幂等：已存在的数据会被跳过（通过唯一字段去重或 upsert）。
不应在 FastAPI 启动事件中调用 — 多 worker 部署会有竞态。
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import func, select

from app.core.security import hash_password
from app.database import AsyncSessionLocal
from app.models.employee import Employee
from app.models.role import Permission, PermissionCode, Role, RolePermission, EmployeeRole
from app.models.tenant import Tenant

logger = logging.getLogger("bootstrap")

# 默认超管（仅在无任何员工时创建，安全起见生产环境部署后应修改密码）
_DEFAULT_ADMIN = {
    "email": "admin@fastagent.local",
    "password": "Admin123!",
    "display_name": "超级管理员",
}

# PermissionCode 枚举 → 中文描述映射
_PERMISSION_DESCRIPTIONS = {
    PermissionCode.VIEW_ASSIGNED_CHATS: "查看分配给我的会话",
    PermissionCode.VIEW_ALL_CHATS: "查看所有会话",
    PermissionCode.MANAGE_CONVERSATIONS: "管理会话（回复/转接/关闭）",
    PermissionCode.VIEW_CONTACTS: "查看客户/联系人列表",
    PermissionCode.MANAGE_CONTACTS: "管理客户/联系人（添加/编辑/删除）",
    PermissionCode.EXPORT_CONTACTS: "导出客户列表",
    PermissionCode.VIEW_PRODUCTS: "查看商品列表",
    PermissionCode.MANAGE_PRODUCTS: "管理商品（添加/编辑/删除）",
    PermissionCode.VIEW_ORDERS: "查看订单列表",
    PermissionCode.MANAGE_ORDERS: "管理订单（创建/编辑）",
    PermissionCode.UPDATE_ORDER_STATUS: "更新订单状态",
    PermissionCode.VIEW_KB: "查看知识库",
    PermissionCode.MANAGE_KB: "管理知识库（上传/编辑/删除）",
    PermissionCode.VIEW_MARKETING: "查看营销资料",
    PermissionCode.MANAGE_MARKETING: "管理营销资料",
    PermissionCode.VIEW_IMAGES: "查看图片库",
    PermissionCode.MANAGE_IMAGES: "管理图片库",
    PermissionCode.VIEW_EMPLOYEES: "查看员工列表",
    PermissionCode.MANAGE_EMPLOYEES: "管理员工（添加/编辑/删除）",
    PermissionCode.MANAGE_ROLES: "管理角色与权限",
    PermissionCode.VIEW_BILLING: "查看计费信息",
    PermissionCode.MANAGE_BILLING: "管理计费设置",
    PermissionCode.VIEW_ANALYTICS: "查看数据分析",
    PermissionCode.EXPORT_ANALYTICS: "导出分析报告",
    PermissionCode.VIEW_CHANNELS: "查看渠道配置",
    PermissionCode.MANAGE_CHANNELS: "管理渠道配置",
    PermissionCode.MANAGE_LLM_CONFIG: "管理 LLM 配置",
    PermissionCode.MANAGE_SENSITIVE_WORDS: "管理敏感词",
    PermissionCode.MANAGE_TENANTS: "管理租户（平台专有）",
    PermissionCode.MANAGE_PLANS: "管理套餐（平台专有）",
    PermissionCode.VIEW_AUDIT_LOGS: "查看审计日志（平台专有）",
    PermissionCode.MANAGE_BACKUPS: "管理备份（平台专有）",
    PermissionCode.MANAGE_SYSTEM_SETTINGS: "管理系统设置（平台专有）",
    PermissionCode.EXPORT_DATA: "导出平台数据（平台专有）",
}


async def _seed_permissions(db) -> int:
    """写入权限码到 permissions 表，返回写入条数。"""
    existing = await db.scalar(select(func.count(Permission.id)))
    if existing and existing > 0:
        logger.info("权限码已存在 (%s 条)，跳过", existing)
        return 0

    count = 0
    for code in PermissionCode:
        desc = _PERMISSION_DESCRIPTIONS.get(code)
        db.add(Permission(
            id=hash(code.value) % (10 ** 15),
            code=code.value,
            name=code.name.replace("_", " ").title(),
            description=desc,
        ))
        count += 1
    await db.commit()
    logger.info("权限码已初始化 (%s 条)", count)
    return count


async def _ensure_platform_tenant(db) -> Tenant:
    """确保平台默认租户存在。"""
    tenant = await db.scalar(select(Tenant).where(Tenant.slug == "fastagent"))
    if tenant is None:
        tenant = Tenant(name="FastAgent 平台", slug="fastagent")
        db.add(tenant)
        await db.flush()
        logger.info("平台默认租户已创建 (slug=fastagent)")
    return tenant


async def _ensure_superadmin(db, tenant: Tenant) -> bool:
    """若无员工则创建默认超管。返回是否创建。"""
    count = await db.scalar(select(func.count(Employee.id)))
    if count and count > 0:
        logger.info("员工已存在 (%s 人)，跳过超管创建", count)
        return False

    admin = Employee(
        tenant_id=tenant.id,
        email=_DEFAULT_ADMIN["email"],
        hashed_password=hash_password(_DEFAULT_ADMIN["password"]),
        display_name=_DEFAULT_ADMIN["display_name"],
        is_superuser=True,
    )
    db.add(admin)
    await db.commit()
    logger.info("默认超管已创建 (%s)", _DEFAULT_ADMIN["email"])
    return True


async def _init_system_settings(db) -> None:
    """初始化系统默认设置。"""
    from app.services.system_service import init_default_settings
    await init_default_settings(db)


async def _seed_intent_samples() -> None:
    """将平台默认意图样本写入 Qdrant 向量库（幂等 upsert）。

    意图样本是向量语义召回的基础。没有意图样本，所有用户消息只能降级到
    本地文本相似度兜底匹配，准确率会明显下降。此函数在 bootstrap 阶段主动索引，
    避免将首次请求用户的耗时摊到第一个真实客户消息上。
    """
    from app.config import settings
    from app.ai.classifier.intent_examples import DEFAULT_INTENT_EXAMPLES
    from app.ai.rag.vector_search import VectorDomain, VectorSearchService

    qdrant_ok = settings.QDRANT_ENABLED and settings.QDRANT_URL
    embed_ok = settings.AI_EMBEDDING_ENABLED and settings.AI_EMBEDDING_BASE_URL
    if not qdrant_ok or not embed_ok:
        logger.info(
            "意图样本索引跳过：QDRANT_ENABLED=%s AI_EMBEDDING_ENABLED=%s",
            settings.QDRANT_ENABLED,
            settings.AI_EMBEDDING_ENABLED,
        )
        return

    vs = VectorSearchService()
    await vs.delete_points(domain=VectorDomain.INTENT_SAMPLE, tenant_id=0)

    indexed = 0
    for example in DEFAULT_INTENT_EXAMPLES:
        point_id = await vs.upsert_text(
            domain=VectorDomain.INTENT_SAMPLE,
            tenant_id=0,
            business_id=f"{example.intent}:{example.example_text}",
            text=example.example_text,
            payload={
                "intent": example.intent,
                "label": example.label,
                "route": example.route,
                "skill": example.skill,
                "example_text": example.example_text,
                "is_active": True,
                "source": "platform_default",
            },
        )
        if point_id:
            indexed += 1
    logger.info("意图样本已索引到 Qdrant：total=%s indexed=%s", len(DEFAULT_INTENT_EXAMPLES), indexed)


async def bootstrap() -> None:
    """执行平台基础数据初始化（幂等）。"""
    async with AsyncSessionLocal() as db:
        try:
            await _seed_permissions(db)
            tenant = await _ensure_platform_tenant(db)
            await _ensure_superadmin(db, tenant)
            await _init_system_settings(db)
            await _seed_intent_samples()
            logger.info("bootstrap 完成")
        except Exception:
            await db.rollback()
            logger.exception("bootstrap 失败")
            raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    asyncio.run(bootstrap())
