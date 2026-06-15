"""运营支撑 API — 通知、敏感词管理、审计日志。

职责
----
本模块提供运营支撑相关的 REST API 端点：
  - 站内通知（/notifications）：已登录坐席查看和标记通知，scope 到本租户
  - 租户级敏感词（/sensitive-words）：租户管理员管理本租户的敏感词规则，需 MANAGE_SENSITIVE_WORDS 权限
  - 平台级敏感词（/admin/sensitive-words）：超管管理系统级通用敏感词规则（tenant_id IS NULL）
  - 审计日志（/admin/audit-logs）：仅超管，跨租户查看全平台操作审计记录
  - 登录历史（/admin/login-histories）：仅超管，查看全平台登录尝试记录

访问角色
--------
- 通知接口：已登录员工即可访问（get_current_user），自动 scope 到本租户
- 租户级敏感词：需 MANAGE_SENSITIVE_WORDS 权限
- 平台级敏感词/审计日志/登录历史：仅超管（require_superuser），跨租户视图
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.database import get_db
from app.dependencies import require_permission, require_superuser, require_tenant_user
from app.models.employee import Employee
from app.models.role import PermissionCode
from app.schemas.operations import (
    AuditLogResponse,
    LoginHistoryResponse,
    NotificationResponse,
    SensitiveWordCreate,
    SensitiveWordResponse,
    SensitiveWordUpdate,
)
from app.services import operations_service as service

router = APIRouter(tags=["运营支撑"])


# ---------------------------------------------------------------------------
# 内部序列化辅助函数
# ---------------------------------------------------------------------------

def _notification(item) -> NotificationResponse:
    """将 SystemNotification ORM 对象转换为 NotificationResponse 输出模型。"""
    return NotificationResponse(
        id=item.id, type=item.type, level=item.level, title=item.title,
        content=item.content, resource_type=item.resource_type,
        resource_id=item.resource_id, metadata=item.metadata_ or {},
        is_read=item.is_read, read_at=item.read_at, created_at=item.created_at,
    )


# ===========================================================================
# 站内通知
# ===========================================================================

@router.get("/notifications")
async def list_notifications(
    unread_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_tenant_user),
):
    """获取当前坐席的通知列表（定向通知 + 租户广播通知）。

    权限：已登录员工（get_current_user）。
    租户隔离：通过 current_user.tenant_id 自动 scope 到本租户。
    参数：
      unread_only — 是否仅查询未读通知
    返回：分页的通知列表，含 type、level、title、content 等字段。
    """
    items, total = await service.list_notifications(
        db, current_user.tenant_id, current_user.id,
        unread_only=unread_only, page=page, page_size=page_size,
    )
    return {
        "items": [_notification(item) for item in items],
        "total": total, "page": page, "pageSize": page_size,
    }


@router.put("/notifications/{item_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_tenant_user),
):
    """将指定通知标记为已读。

    权限：已登录员工。
    租户隔离：只能标记自己的定向通知或本租户的广播通知。
    参数：item_id — 通知 ID。
    返回：更新后的通知对象，若不存在或不属于当前坐席返回 404。
    """
    item = await service.mark_notification_read(
        db, current_user.tenant_id, current_user.id, item_id,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="通知不存在")
    return _notification(item)


# ===========================================================================
# 租户级敏感词管理
# ===========================================================================

@router.get("/sensitive-words", response_model=list[SensitiveWordResponse])
async def list_sensitive_words(
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_SENSITIVE_WORDS)),
):
    """查询本租户的敏感词规则列表。

    权限：MANAGE_SENSITIVE_WORDS。
    租户隔离：通过 current_user.tenant_id 自动 scope。
    返回：按创建时间倒序排列的敏感词规则列表。
    """
    return await service.list_sensitive_words(db, current_user.tenant_id)


@router.post("/sensitive-words", response_model=SensitiveWordResponse, status_code=status.HTTP_201_CREATED)
async def create_sensitive_word(
    body: SensitiveWordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_SENSITIVE_WORDS)),
):
    """创建本租户的敏感词规则。

    权限：MANAGE_SENSITIVE_WORDS。
    租户隔离：敏感词自动绑定到 current_user.tenant_id。
    校验：同一租户内敏感词文本不允许重复，重复返回 400。
    """
    try:
        return await service.create_sensitive_word(db, current_user.tenant_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/sensitive-words/{item_id}", response_model=SensitiveWordResponse)
async def update_sensitive_word(
    item_id: int,
    body: SensitiveWordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_SENSITIVE_WORDS)),
):
    """部分更新本租户的敏感词规则（仅修改传入的非空字段）。

    权限：MANAGE_SENSITIVE_WORDS。
    租户隔离：只能修改本租户的规则。
    参数：item_id — 敏感词规则 ID。
    返回：更新后的规则，不存在或不属于本租户返回 404。
    """
    item = await service.update_sensitive_word(db, current_user.tenant_id, item_id, body)
    if item is None:
        raise HTTPException(status_code=404, detail="敏感词不存在")
    return item


# ===========================================================================
# 平台级审计与管理（仅超管）
# ===========================================================================

@router.get("/admin/audit-logs")
async def list_audit_logs(
    tenant_id: int | None = Query(default=None),
    action: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """跨租户查询全平台审计日志。

    权限：require_superuser — 仅超级管理员可访问。
    参数：
      tenant_id — 可选，按租户过滤；不传返回全平台数据
      action — 可选，按操作类型过滤（如 "login"、"create_order"）
    返回：分页的审计日志列表，含操作类型、资源类型、操作详情、IP 等字段。
    设计意图：审计日志使用独立事务写入，即使业务事务回滚也不会丢失。
    """
    items, total = await service.list_audit_logs(
        db, tenant_id=tenant_id, action=action, page=page, page_size=page_size,
    )
    return {
        "items": [AuditLogResponse.model_validate(item, from_attributes=True) for item in items],
        "total": total, "page": page, "pageSize": page_size,
    }


@router.get("/admin/login-histories")
async def list_login_histories(
    email: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """查询全平台登录历史记录。

    权限：require_superuser — 仅超级管理员可访问。
    参数：
      email — 可选，按登录邮箱模糊搜索（ILIKE 匹配）
    返回：分页的登录历史列表，含邮箱、成功/失败状态、失败原因、IP 地址等。
    安全说明：不记录密码等敏感凭据，仅记录邮箱和成功/失败状态。
    """
    items, total = await service.list_login_histories(
        db, email=email, page=page, page_size=page_size,
    )
    return {
        "items": [LoginHistoryResponse.model_validate(item, from_attributes=True) for item in items],
        "total": total, "page": page, "pageSize": page_size,
    }


@router.get("/admin/sensitive-words", response_model=list[SensitiveWordResponse])
async def list_platform_sensitive_words(
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """查询系统级（平台通用）敏感词规则列表。

    权限：require_superuser。
    返回：tenant_id IS NULL 的系统级规则，适用于全平台所有租户。
    """
    return await service.list_sensitive_words(db, None)


@router.post("/admin/sensitive-words", response_model=SensitiveWordResponse, status_code=status.HTTP_201_CREATED)
async def create_platform_sensitive_word(
    body: SensitiveWordCreate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """创建系统级（平台通用）敏感词规则。

    权限：require_superuser。
    参数：body — 敏感词创建请求体，tenant_id 自动设为 None（系统级）。
    校验：系统级规则中敏感词文本不允许重复，重复返回 400。
    """
    try:
        return await service.create_sensitive_word(db, None, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/admin/sensitive-words/{item_id}", response_model=SensitiveWordResponse)
async def update_platform_sensitive_word(
    item_id: int,
    body: SensitiveWordUpdate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """部分更新系统级敏感词规则。

    权限：require_superuser。
    参数：item_id — 敏感词规则 ID。
    返回：更新后的规则，不存在或不属于系统级规则返回 404。
    """
    item = await service.update_sensitive_word(db, None, item_id, body)
    if item is None:
        raise HTTPException(status_code=404, detail="敏感词不存在")
    return item
