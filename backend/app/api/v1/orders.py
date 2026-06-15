"""订单管理 API — Phase 10"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.database import get_db
from app.dependencies import require_permission
from app.models.employee import Employee
from app.models.role import PermissionCode
from app.schemas.order import (
    OrderBatchStatusTransition,
    OrderCreate,
    OrderListResponse,
    OrderResponse,
    OrderStatusTransition,
    OrderUpdate, OrderItemResponse,
)
from app.services import order_service

router = APIRouter(prefix="/orders", tags=["订单"])


def _to_response(order) -> OrderResponse:
    return OrderResponse(
        id=order.id,
        tenant_id=order.tenant_id,
        contact_id=order.contact_id,
        conversation_id=order.conversation_id,
        employee_id=order.employee_id,
        status=order.status,
        total_amount=float(order.total_amount),
        discount_amount=float(order.discount_amount),
        payable_amount=float(order.payable_amount),
        shipping_address=order.shipping_address,
        receiver_name=order.receiver_name,
        receiver_phone=order.receiver_phone,
        remark=order.remark,
        metadata_=order.metadata_,
        created_by_type=order.created_by_type,
        created_by_employee_id=order.created_by_employee_id,
        confirmed_at=order.confirmed_at,
        shipped_at=order.shipped_at,
        signed_at=order.signed_at,
        cancelled_at=order.cancelled_at,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=[
            OrderItemResponse(
                id=item.id,
                order_id=item.order_id,
                product_id=item.product_id,
                product_snapshot=item.product_snapshot,
                quantity=item.quantity,
                unit_price=float(item.unit_price),
                subtotal=float(item.subtotal),
                created_at=item.created_at,
            )
            for item in (order.items or [])
        ],
        contact_name=getattr(order, "_contact_name", None),
    )


@router.get("", response_model=OrderListResponse)
async def list_orders(
    contact_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    employee_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.VIEW_ORDERS)),
):
    """订单列表"""
    items, total = await order_service.list_orders(
        db,
        current_user.tenant_id,
        contact_id=contact_id,
        status=status,
        employee_id=employee_id,
        page=page,
        page_size=page_size,
    )
    return OrderListResponse(
        items=[_to_response(o) for o in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.VIEW_ORDERS)),
):
    """订单详情"""
    order = await order_service.get_order(db, order_id, current_user.tenant_id)
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    return _to_response(order)


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    body: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_ORDERS)),
):
    """创建订单"""
    try:
        order = await order_service.create_order(
            db,
            current_user.tenant_id,
            body,
            created_by_employee_id=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_response(order)


@router.put("/{order_id}", response_model=OrderResponse)
async def update_order(
    order_id: int,
    body: OrderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_ORDERS)),
):
    """修改订单（增删商品/改地址/改备注/改优惠）"""
    try:
        order = await order_service.update_order(
            db, order_id, current_user.tenant_id, body
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    return _to_response(order)


@router.patch("/{order_id}/status", response_model=OrderResponse)
async def transition_order_status(
    order_id: int,
    body: OrderStatusTransition,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.UPDATE_ORDER_STATUS)),
):
    """订单状态流转"""
    try:
        order = await order_service.transition_order_status(
            db, order_id, current_user.tenant_id, body.status
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    return _to_response(order)


@router.patch("/batch/status", response_model=dict)
async def batch_transition_status(
    body: OrderBatchStatusTransition,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.UPDATE_ORDER_STATUS)),
):
    """批量状态流转"""
    succeeded, failed = await order_service.batch_transition_status(
        db, current_user.tenant_id, body.order_ids, body.status
    )
    return {"succeeded": [str(s) for s in succeeded], "failed": [str(f) for f in failed]}


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_ORDERS)),
):
    """取消订单"""
    ok = await order_service.cancel_order(db, order_id, current_user.tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="订单不存在或无法取消")
