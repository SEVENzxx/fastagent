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
from app.integrations.database import AsyncSessionLocal
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



async def _seed_permissions(db) -> int:
    """写入权限码到 permissions 表（幂等 upsert），返回新增条数。"""
    count = 0
    for code in PermissionCode:
        existing = await db.scalar(select(Permission).where(Permission.code == code.value))
        if existing:
            continue
        desc = code.label
        db.add(Permission(
            id=hash(code.value) % (10 ** 15),
            code=code.value,
            name=code.name.replace("_", " ").title(),
            description=desc,
        ))
        count += 1
    if count > 0:
        await db.commit()
    logger.info("权限码检查完成：新增 %s 条", count)
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

    增强的安全策略：
    1. 先检查是否已存在且数量匹配 → 跳过，避免重复。
    2. 先发一条测试 embedding 确认服务可用，再执行删除。
    3. 删除 + 重索引走完才返回，确保 bootstrap 结束时数据完整。

    SCHEMA_VERSION 变更时增量升级，不会误删 tenant>0 的租户样本。
    """
    from app.config import settings
    from app.ai.recognition.examples import DEFAULT_INTENT_EXAMPLES, SCHEMA_VERSION
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
    expected = len(DEFAULT_INTENT_EXAMPLES)

    # ── 1: 检查是否已存在且是最新版本 ──
    try:
        existing = await vs.count_points(domain=VectorDomain.INTENT_SAMPLE, tenant_id=0)
        if existing == expected:
            logger.info(
                "意图样本已存在且数量匹配：count=%s schema_version=%s，跳过",
                existing, SCHEMA_VERSION,
            )
            return
        logger.info("意图样本需要更新：现有=%s 预期=%s", existing, expected)
    except Exception:
        logger.info("无法获取现有样本计数，将执行全量索引")

    # ── 2: 发送测试 embedding 确认服务可用 ──
    try:
        test_vec = await vs.embedding.embed("测试")
        if not test_vec or len(test_vec) != settings.AI_EMBEDDING_DIMENSION:
            logger.error("Embedding 服务返回格式异常，跳过意图样本索引")
            return
    except Exception as exc:
        logger.error("Embedding 服务不可用，跳过意图样本索引：%s", exc)
        return

    # ── 3: 清理旧数据并重新索引 ──
    await vs.delete_points(domain=VectorDomain.INTENT_SAMPLE, tenant_id=0)

    indexed = 0
    for example in DEFAULT_INTENT_EXAMPLES:
        point_id = await vs.upsert_text(
            domain=VectorDomain.INTENT_SAMPLE,
            tenant_id=0,
            business_id=f"{example.scenario_id}:{example.example_text}",
            text=example.example_text,
            payload={
                "scenario_id": example.scenario_id,
                "label": example.label,
                "risk_level": example.risk_level,
                "example_text": example.example_text,
                "schema_version": SCHEMA_VERSION,
                "is_active": True,
                "source": "platform_default",
            },
        )
        if point_id:
            indexed += 1

    if indexed == expected:
        logger.info(
            "意图样本全量索引成功：total=%s indexed=%s schema_version=%s",
            expected, indexed, SCHEMA_VERSION,
        )
    else:
        logger.warning(
            "意图样本索引部分失败：total=%s indexed=%s schema_version=%s",
            expected, indexed, SCHEMA_VERSION,
        )


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
    from app.common.trace.context import ensure_trace_id, reset_trace_id
    from app.logging_config import setup_logging

    setup_logging()
    ensure_trace_id()
    try:
        asyncio.run(bootstrap())
    finally:
        reset_trace_id()
