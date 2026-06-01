"""平台 Admin API — 仪表盘、套餐/LLM 配置/租户 CRUD、跨租户业务数据。

职责
----
本模块提供超级管理员后台的全部 REST API 端点：
  - 平台仪表盘（/admin/dashboard）：核心运营指标聚合展示
  - 套餐管理（/admin/plans）：平台级套餐资源的 CRUD
  - LLM 配置管理（/admin/llm-configs）：LLM 供应商配置的 CRUD
  - 租户管理（/admin/tenants）：创建/更新/查询租户
  - 跨租户业务查询（/admin/business/*）：会话、消息、订单、知识库文档的跨租户查看

访问角色
--------
所有端点 require_superuser，仅超级管理员可访问。
跨租户查询可看到全平台所有租户的数据，不经过租户隔离过滤。
API Key 在响应中仅返回 has_api_key 布尔值，不传密文或明文。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_superuser
from app.models.employee import Employee
from app.schemas.admin import (
    AdminDashboardResponse,
    AdminConversationResponse,
    AdminKnowledgeDocResponse,
    AdminMessageResponse,
    AdminOrderResponse,
    LLMConfigCreate,
    LLMConfigResponse,
    LLMConfigUpdate,
    PlanCreate,
    PlanResponse,
    PlanUpdate,
    TenantCreate,
    TenantCreateResponse,
    TenantResponse,
    TenantUpdate,
)
from app.schemas.system import (
    BackupRecordResponse,
    DbHealthResponse,
    SystemSettingsResponse,
    SystemSettingsUpdate,
)
from app.services import admin_service
from app.services import system_service

router = APIRouter(prefix="/admin", tags=["平台 Admin"])


# ---------------------------------------------------------------------------
# 内部序列化辅助函数
# ---------------------------------------------------------------------------

def _plan(item) -> PlanResponse:
    """将 Plan ORM 对象转换为 PlanResponse 输出模型。"""
    return PlanResponse.model_validate(item, from_attributes=True)


def _llm(item) -> LLMConfigResponse:
    """将 LLMConfig ORM 对象转换为 LLMConfigResponse 输出模型。

    API Key 仅返回 has_api_key 布尔值（是否已配置密钥），不传输密文或明文。
    """
    return LLMConfigResponse(
        id=item.id, name=item.name, provider=item.provider, api_base=item.api_base,
        model=item.model, pricing=item.pricing or {}, purpose=item.purpose,
        is_active=item.is_active, has_api_key=bool(item.api_key_encrypted),
        created_at=item.created_at, updated_at=item.updated_at,
    )


def _tenant(item) -> TenantResponse:
    """将 Tenant ORM 对象转换为 TenantResponse 输出模型。

    包含通过 _attach_tenant_names 预加载的 _plan_name 和 _selected_llm_config_name 属性。
    """
    return TenantResponse(
        id=item.id, name=item.name, slug=item.slug, plan_id=item.plan_id,
        plan_name=getattr(item, "_plan_name", None), plan_expires_at=item.plan_expires_at,
        custom_prompt=item.custom_prompt, selected_llm_config_id=item.selected_llm_config_id,
        selected_llm_config_name=getattr(item, "_selected_llm_config_name", None),
        is_active=item.is_active, created_at=item.created_at, updated_at=item.updated_at,
    )


# ===========================================================================
# 平台仪表盘
# ===========================================================================

@router.get("/dashboard", response_model=AdminDashboardResponse)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """获取平台仪表盘核心运营指标。

    权限：require_superuser — 仅超级管理员可访问。
    返回：租户总数、活跃租户数、套餐数、LLM 配置数、会话总数、订单总数等聚合数据。
    """
    return await admin_service.dashboard(db)


# ===========================================================================
# 套餐管理 CRUD
# ===========================================================================

@router.get("/plans", response_model=list[PlanResponse])
async def list_plans(
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """查询所有套餐列表。

    权限：require_superuser。
    返回：按创建时间倒序排列的套餐列表，含名称、限额配置、价格等信息。
    """
    return [_plan(item) for item in await admin_service.list_plans(db)]


@router.post("/plans", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
async def create_plan(
    body: PlanCreate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """创建新套餐。

    权限：require_superuser。
    校验：套餐名称全局唯一，重复返回 400。
    """
    try:
        return _plan(await admin_service.create_plan(db, body))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/plans/{item_id}", response_model=PlanResponse)
async def update_plan(
    item_id: int,
    body: PlanUpdate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """部分更新套餐信息。

    权限：require_superuser。
    参数：item_id — 套餐 ID。
    返回：更新后的套餐信息，不存在返回 404。
    """
    item = await admin_service.update_plan(db, item_id, body)
    if item is None:
        raise HTTPException(status_code=404, detail="套餐不存在")
    return _plan(item)


# ===========================================================================
# LLM 配置管理 CRUD
# ===========================================================================

@router.get("/llm-configs", response_model=list[LLMConfigResponse])
async def list_llm_configs(
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """查询所有 LLM 配置列表。

    权限：require_superuser。
    安全说明：响应中仅返回 has_api_key 布尔值（是否已配置密钥），不传输明文或密文 API Key。
    """
    return [_llm(item) for item in await admin_service.list_llm_configs(db)]


@router.post("/llm-configs", response_model=LLMConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_llm_config(
    body: LLMConfigCreate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """创建新的 LLM 供应商配置。

    权限：require_superuser。
    安全机制：API Key 入库前通过 Fernet 加密，入库后只存密文（api_key_encrypted）。
    """
    return _llm(await admin_service.create_llm_config(db, body))


@router.patch("/llm-configs/{item_id}", response_model=LLMConfigResponse)
async def update_llm_config(
    item_id: int,
    body: LLMConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """部分更新 LLM 配置。

    权限：require_superuser。
    参数：item_id — LLM 配置 ID。
    注意：api_key 仅在前端显式传入时才会重新加密更新，传空字符串不会清除已有密钥。
    """
    item = await admin_service.update_llm_config(db, item_id, body)
    if item is None:
        raise HTTPException(status_code=404, detail="LLM 配置不存在")
    return _llm(item)


# ===========================================================================
# 租户管理 CRUD
# ===========================================================================

@router.get("/tenants", response_model=list[TenantResponse])
async def list_tenants(
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """查询所有租户列表（排除软删除）。

    权限：require_superuser。
    返回：按创建时间倒序排列的租户列表，含关联套餐名称和 LLM 配置名称。
    """
    return [_tenant(item) for item in await admin_service.list_tenants(db)]


@router.post("/tenants", response_model=TenantCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """创建新租户并自动生成租户管理员账号。

    权限：require_superuser — 仅超级管理员可创建租户。

    在一个事务中完成：
      1. 创建租户（校验 slug 唯一性和外键有效性）
      2. 创建租户管理员员工账号（is_superuser=False）
      3. 初始化"管理员"和"坐席"两个默认角色
      4. 自动分配业务权限（排除平台专有权限）

    返回：租户信息 + 管理员邮箱和密码（密码仅在创建时返回一次）。
    超管应将账号密码安全交付给租户管理员。
    """
    try:
        result = await admin_service.create_tenant(db, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    tenant_resp = _tenant(result["tenant"])
    return TenantCreateResponse(
        **tenant_resp.model_dump(),
        admin_email=result["admin_email"],
        admin_password=result["admin_password"],
    )


@router.patch("/tenants/{item_id}", response_model=TenantResponse)
async def update_tenant(
    item_id: int,
    body: TenantUpdate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """部分更新租户信息。

    权限：require_superuser。
    参数：item_id — 租户 ID。
    校验：若传入 plan_id 或 selected_llm_config_id，校验引用的外键存在。
    """
    try:
        item = await admin_service.update_tenant(db, item_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if item is None:
        raise HTTPException(status_code=404, detail="租户不存在")
    return _tenant(item)


# ===========================================================================
# 跨租户业务数据查询（平台级视角）
# ===========================================================================

@router.get("/business/conversations")
async def list_business_conversations(
    tenant_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    keyword: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """平台级跨租户会话列表。

    权限：require_superuser。
    参数：
      tenant_id — 可选，按租户过滤
      status — 可选，按会话状态过滤
      keyword — 可选，按联系人姓名或电话模糊搜索
    返回：分页的会话摘要列表，含租户名称、联系人名称、坐席名称、最新消息预览。
    """
    items, total = await admin_service.list_cross_tenant_conversations(
        db, tenant_id=tenant_id, status=status_filter, keyword=keyword,
        page=page, page_size=page_size,
    )
    return {
        "items": [AdminConversationResponse(**item) for item in items],
        "total": total, "page": page, "pageSize": page_size,
    }


@router.get("/business/conversations/{conversation_id}/messages")
async def list_business_messages(
    conversation_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """平台级会话消息下钻。

    权限：require_superuser。
    参数：conversation_id — 会话 ID。
    返回：按时间正序排列的消息列表（对话时间线顺序）。会话不存在返回空列表。
    """
    items, total = await admin_service.list_cross_tenant_messages(
        db, conversation_id, page=page, page_size=page_size,
    )
    data = [
        AdminMessageResponse(
            id=item.id, conversation_id=item.conversation_id,
            sender_type=item.sender_type, content_type=item.content_type,
            content=item.content, is_recalled=item.is_recalled,
            created_at=item.created_at,
        )
        for item in items
    ]
    return {"items": data, "total": total, "page": page, "pageSize": page_size}


@router.get("/business/orders")
async def list_business_orders(
    tenant_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """平台级跨租户订单列表。

    权限：require_superuser。
    参数：
      tenant_id — 可选，按租户过滤
      status — 可选，按订单状态过滤
    返回：分页的订单摘要列表，含租户名称、联系人名称、应付金额等信息。
    """
    items, total = await admin_service.list_cross_tenant_orders(
        db, tenant_id=tenant_id, status=status_filter, page=page, page_size=page_size,
    )
    return {
        "items": [AdminOrderResponse(**item) for item in items],
        "total": total, "page": page, "pageSize": page_size,
    }


@router.get("/business/knowledge-docs")
async def list_business_knowledge_docs(
    tenant_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """平台级跨租户知识库文档列表。

    权限：require_superuser。
    参数：
      tenant_id — 可选，按租户过滤
      status — 可选，按文档处理状态过滤（pending/processing/completed/failed）
    返回：分页的文档摘要列表，含租户名称、标题、处理状态、分块数等信息。
    """
    items, total = await admin_service.list_cross_tenant_knowledge_docs(
        db, tenant_id=tenant_id, status=status_filter, page=page, page_size=page_size,
    )
    return {
        "items": [AdminKnowledgeDocResponse(**item) for item in items],
        "total": total, "page": page, "pageSize": page_size,
    }


# ===========================================================================
# 系统运维 — 系统设置、数据库监控、备份管理（仅超管）
# ===========================================================================

@router.get("/system/settings")
async def get_system_settings(
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """获取平台全局系统设置。

    权限：require_superuser。
    返回：所有系统设置键值对，含默认值（数据库中没有的 key 返回默认值）。
    """
    settings = await system_service.get_all_settings(db)
    return {"settings": [
        {"key": k, "value": v} for k, v in settings.items()
    ]}


@router.put("/system/settings")
async def update_system_settings(
    body: SystemSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """批量更新系统设置。

    权限：require_superuser。
    参数：body.settings — 键值对字典，如 {"max_file_upload_mb": "20", "rate_limit_per_minute": "100"}。
    说明：未传入的 key 保持原值不变，不存在的 key 自动创建。
    """
    await system_service.update_settings(db, body)
    return {"ok": True}


@router.get("/system/db-health", response_model=DbHealthResponse)
async def get_db_health(
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """获取数据库健康状态快照。

    权限：require_superuser。
    返回：当前连接数、最大连接、DB 大小、运行时长、慢查询数和索引命中率。
    技术说明：直接查询 PostgreSQL 系统视图 pg_stat_activity / pg_database / pg_stat_user_tables。
    """
    return await system_service.get_db_health(db)


@router.get("/system/backups")
async def list_backups(
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """查询备份记录列表。

    权限：require_superuser。
    返回：按创建时间倒序排列的备份记录列表，含文件名、大小(MB)、类型、状态等。
    """
    return await system_service.list_backups(db)


@router.post("/system/backups", status_code=status.HTTP_201_CREATED)
async def create_backup(
    type: str = Query(default="full"),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """创建数据库备份。

    权限：require_superuser。
    参数：type — 备份类型，"full"(全量，默认) 或 "schema"(仅结构)。
    执行模式：API 立即返回备份记录（status=running），后台异步执行 pg_dump。
    完成后自动更新备份记录的 status 和大小信息。
    """
    record = await system_service.create_backup(db, type)
    return {
        "id": str(record.id), "name": record.name, "status": record.status,
        "type": record.type, "created_at": record.created_at.isoformat(),
    }


@router.post("/system/backups/{backup_id}/restore")
async def restore_backup(
    backup_id: int,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """从指定备份恢复数据库。

    权限：require_superuser。
    参数：backup_id — 备份记录 ID。
    警告：这是高危操作，会用备份数据覆盖当前数据库！仅允许恢复 status='completed' 的备份。
    """
    record = await system_service.restore_backup(db, backup_id)
    if record is None:
        raise HTTPException(status_code=404, detail="备份不存在或状态不可恢复")
    return {"ok": True, "message": f"开始从备份 #{backup_id} 恢复数据库"}


@router.delete("/system/backups/{backup_id}")
async def delete_backup(
    backup_id: int,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """删除备份记录及对应磁盘文件。

    权限：require_superuser。
    参数：backup_id — 备份记录 ID。
    说明：先删除磁盘上的备份文件（失败不阻断），再删除数据库记录。
    """
    record = await system_service.delete_backup(db, backup_id)
    if record is None:
        raise HTTPException(status_code=404, detail="备份不存在")
    return {"ok": True}
