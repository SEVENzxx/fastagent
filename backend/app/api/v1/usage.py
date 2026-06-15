"""
用量与分析 API — 租户侧数据看板、LLM 用量和平台侧用量审计路由模块。

职责
----
本模块提供用量监测与数据分析相关接口：
  - 租户仪表盘（Tenant Dashboard）：本租户的关键业务指标聚合视图。
  - 租户 LLM 用量（Tenant Usage）：本租户的 LLM 调用量、token 消耗分页查询。
  - 平台用量审计（Admin Usage）：超级管理员跨租户查看所有租户的 LLM 用量。

访问角色
--------
- 租户仪表盘（/analytics/dashboard）：需要 VIEW_BILLING 权限
- 租户用量（/billing/usage）：需要 VIEW_BILLING 权限
- 平台用量审计（/admin/usage）：仅 **超级管理员（superuser）** 可访问，跨租户视图
- 所有租户侧端点的数据均通过 `current_user.tenant_id` 做租户隔离
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.database import get_db
from app.dependencies import require_permission, require_superuser
from app.models.employee import Employee
from app.models.role import PermissionCode
from app.schemas.usage import LLMUsageResponse, TenantDashboardResponse
from app.services import usage_service

# APIRouter 实例，无统一前缀（通过路径区分功能），OpenAPI 文档分组标签为"用量与分析"
router = APIRouter(tags=["用量与分析"])


# ===========================================================================
# 租户仪表盘
# ===========================================================================

@router.get("/analytics/dashboard", response_model=TenantDashboardResponse)
async def tenant_dashboard(db: AsyncSession = Depends(get_db), current_user: Employee = Depends(require_permission(PermissionCode.VIEW_BILLING))):
    """获取本租户的数据仪表盘。

    权限：VIEW_BILLING — 需要计费/用量查看权限。
    租户隔离：通过 current_user.tenant_id 自动 scope 到本租户。
    返回：本租户的关键业务指标聚合数据，通常包括：
      - 活跃会话数、消息总量
      - LLM 调用次数、token 消耗量
      - 知识库文档数、商品数
      - 等综合统计指标
    """
    return await usage_service.tenant_dashboard(db, current_user.tenant_id)


# ===========================================================================
# 租户 LLM 用量查询
# ===========================================================================

@router.get("/billing/usage")
async def tenant_usage(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.VIEW_BILLING)),
):
    """查询本租户的 LLM 用量记录。

    权限：VIEW_BILLING — 需要计费/用量查看权限。
    租户隔离：通过 current_user.tenant_id 自动 scope 到本租户。
    返回：分页的 LLM 调用记录，含每次调用的模型、token 输入/输出量、费用等信息。
    用途：用于租户侧的成本监控和用量分析。
    """
    items, total = await usage_service.list_usage_logs(db, tenant_id=current_user.tenant_id, page=page, page_size=page_size)
    return {"items": [LLMUsageResponse.model_validate(item, from_attributes=True) for item in items], "total": total, "page": page, "pageSize": page_size}


# ===========================================================================
# 平台用量审计（仅超管）
# ===========================================================================

@router.get("/admin/usage")
async def admin_usage(
    tenant_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_superuser),
):
    """跨租户查看全平台 LLM 用量审计数据。

    权限：require_superuser — 仅超级管理员可访问。
    参数：
      tenant_id — 可选，按租户过滤用量记录；不传则返回全平台数据。
    返回：分页的 LLM 调用记录，含租户归属信息。
    用途：用于平台运营方监控全平台 AI 资源消耗，支撑成本核算和异常检测。
    """
    items, total = await usage_service.list_usage_logs(db, tenant_id=tenant_id, page=page, page_size=page_size)
    return {"items": [LLMUsageResponse.model_validate(item, from_attributes=True) for item in items], "total": total, "page": page, "pageSize": page_size}
