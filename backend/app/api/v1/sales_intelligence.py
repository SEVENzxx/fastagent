"""
销售智能 API — 客户 360 画像、会话待办与跟进计划路由模块。

职责
----
本模块提供面向销售场景的智能辅助功能：
  - 客户 360 画像（Contact 360）：聚合联系人基本信息、销售上下文、
    销售记忆、商品上下文、订单、待办和跟进计划，一次性返回给前端工作台。
  - 会话待办（Todo）：与聊天会话关联的待办事项 CRUD。
  - 跟进计划（Followup Plan）：针对联系人的跟进计划创建。

访问角色
--------
- 客户 360 画像查看、待办列表：需要 VIEW_CONTACTS 权限
- 待办创建/更新：需要 MANAGE_CONVERSATIONS 权限
- 跟进计划创建：需要 MANAGE_CONTACTS 权限
- 所有端点的数据均通过 `current_user.tenant_id` 做租户隔离
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.database import get_db
from app.dependencies import require_permission
from app.models.employee import Employee
from app.models.role import PermissionCode
from app.schemas.sales_intelligence import (
    Contact360Response,
    ContactProductContextResponse,
    FollowupPlanCreate,
    FollowupPlanResponse,
    SalesContextResponse,
    SalesMemoryResponse,
    TodoCreate,
    TodoResponse,
    TodoUpdate,
)
from app.services import sales_intelligence_service as service

# APIRouter 实例，所有端点统一前缀 /sales，OpenAPI 文档分组标签为"销售智能"
router = APIRouter(prefix="/sales", tags=["销售智能"])


# ---------------------------------------------------------------------------
# 内部序列化辅助函数
# ---------------------------------------------------------------------------

def _todo_response(item) -> TodoResponse:
    """将 Todo ORM 对象转换为 TodoResponse 输出模型。"""
    return TodoResponse.model_validate(item, from_attributes=True)


def _followup_response(item) -> FollowupPlanResponse:
    """将 FollowupPlan ORM 对象转换为 FollowupPlanResponse 输出模型。"""
    return FollowupPlanResponse.model_validate(item, from_attributes=True)


# ===========================================================================
# 客户 360 画像
# ===========================================================================

@router.get("/contacts/{contact_id}/360", response_model=Contact360Response)
async def get_contact_360(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.VIEW_CONTACTS)),
):
    """获取客户 360 全景画像（聚合视图）。

    权限：VIEW_CONTACTS — 需要联系人查看权限。
    租户隔离：通过 current_user.tenant_id 校验联系人归属。
    设计意图：将工作台右侧画像所需的所有数据一次返回，避免前端串行发起 6-7 个
             独立 API 请求，减少网络往返和加载耗时。
    聚合内容：
      - 联系人基本信息（姓名、电话、地址、标签）
      - 销售上下文（意向等级、预算、预计成交时间等）
      - 销售记忆列表（历史交互要点）
      - 商品上下文列表（关联商品、议价阶段、报价金额等）
      - 关联订单列表
      - 待办事项列表
      - 跟进计划列表
    返回：Contact360Response 聚合响应模型；若联系人不存在则返回 404。
    """
    data = await service.get_contact_360(db, current_user.tenant_id, contact_id)
    if data is None:
        raise HTTPException(status_code=404, detail="联系人不存在")
    return Contact360Response(
        contact_id=data["contact_id"],
        name=data["name"],
        phone=data["phone"],
        address=data["address"],
        tags=data["tags"],
        assigned_employee_name=data["assigned_employee_name"],
        sales_context=SalesContextResponse.model_validate(data["sales_context"], from_attributes=True),
        memories=[SalesMemoryResponse.model_validate(item, from_attributes=True) for item in data["memories"]],
        product_contexts=[
            ContactProductContextResponse(
                id=item.id,
                product_id=item.product_id,
                product_name=name,
                stage=item.stage,
                quoted_price=float(item.quoted_price) if item.quoted_price is not None else None,
                price_level=item.price_level,
                order_id=item.order_id,
            )
            for item, name in data["product_contexts"]
        ],
        orders=data["orders"],
        todos=[_todo_response(item) for item in data["todos"]],
        followups=[_followup_response(item) for item in data["followups"]],
    )


# ===========================================================================
# 会话待办管理
# ===========================================================================

@router.get("/todos", response_model=list[TodoResponse])
async def list_todos(
    conversation_id: int | None = Query(default=None),
    contact_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.VIEW_CONTACTS)),
):
    """获取待办事项列表。

    权限：VIEW_CONTACTS — 需要联系人查看权限。
    租户隔离：通过 current_user.tenant_id 自动 scope 到本租户。
    参数：
      conversation_id — 可选，按关联会话过滤待办。
      contact_id — 可选，按关联联系人过滤待办。
    返回：筛选后的待办列表。
    """
    items = await service.list_todos(db, current_user.tenant_id, conversation_id=conversation_id, contact_id=contact_id)
    return [_todo_response(item) for item in items]


@router.post("/todos", response_model=TodoResponse, status_code=status.HTTP_201_CREATED)
async def create_todo(
    body: TodoCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_CONVERSATIONS)),
):
    """创建新的待办事项。

    权限：MANAGE_CONVERSATIONS — 需要会话管理权限。
    租户隔离：待办自动绑定到 current_user.tenant_id。
    业务逻辑：通常由客服在与客户对话中手动创建，用于标记需后续跟进的事项。
    校验：关联的 contact_id / conversation_id 必须属于同一租户（service 层校验 ValueError）。
    """
    try:
        return _todo_response(await service.create_todo(db, current_user.tenant_id, body))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/todos/{todo_id}", response_model=TodoResponse)
async def update_todo(
    todo_id: int,
    body: TodoUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_CONVERSATIONS)),
):
    """更新待办事项（如标题、截止时间、完成状态等）。

    权限：MANAGE_CONVERSATIONS — 需要会话管理权限。
    租户隔离：通过 tenant_id 校验仅允许修改本租户的待办。
    """
    item = await service.update_todo(db, current_user.tenant_id, todo_id, body)
    if item is None:
        raise HTTPException(status_code=404, detail="待办不存在")
    return _todo_response(item)


# ===========================================================================
# 跟进计划管理
# ===========================================================================

@router.post("/followups", response_model=FollowupPlanResponse, status_code=status.HTTP_201_CREATED)
async def create_followup(
    body: FollowupPlanCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_CONTACTS)),
):
    """创建新的客户跟进计划。

    权限：MANAGE_CONTACTS — 需要联系人管理权限。
    租户隔离：跟进计划自动绑定到 current_user.tenant_id。
    业务逻辑：客服为特定联系人制定跟进策略，含下次跟进时间和跟进内容。
    校验：关联的 contact_id 必须属于本租户（service 层校验 ValueError）。
    """
    try:
        return _followup_response(await service.create_followup(db, current_user.tenant_id, body))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
