"""QA 对 API — Phase 11"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_permission
from app.models.employee import Employee
from app.models.role import PermissionCode
from app.schemas.qa_pair import (
    QAPairCreate,
    QAPairListResponse,
    QAPairResponse,
    QAPairUpdate,
)
from app.services.qa_service import QAService

router = APIRouter(prefix="/qa-pairs", tags=["问答对"])

_qa_service = QAService()


def _to_response(pair) -> QAPairResponse:
    return QAPairResponse(
        id=pair.id,
        question=pair.question,
        answer=pair.answer,
        keywords=pair.keywords,
        is_active=pair.is_active,
        created_by_employee_id=pair.created_by_employee_id,
        created_at=pair.created_at,
        updated_at=pair.updated_at,
    )


@router.get("", response_model=QAPairListResponse)
async def list_qa_pairs(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    is_active: bool | None = None,
    current_user: Employee = Depends(require_permission(PermissionCode.VIEW_KB)),
    db: AsyncSession = Depends(get_db),
):
    """获取 QA 对列表"""
    items, total = await _qa_service.list_pairs(
        db, current_user.tenant_id, skip, limit, is_active
    )
    return QAPairListResponse(
        items=[_to_response(item) for item in items],
        total=total,
    )


@router.get("/{pair_id}", response_model=QAPairResponse)
async def get_qa_pair(
    pair_id: int,
    current_user: Employee = Depends(require_permission(PermissionCode.VIEW_KB)),
    db: AsyncSession = Depends(get_db),
):
    """获取单个 QA 对"""
    pair = await _qa_service.get_pair(db, pair_id, current_user.tenant_id)
    if not pair:
        raise HTTPException(status_code=404, detail="QA对不存在")
    return _to_response(pair)


@router.post("", response_model=QAPairResponse, status_code=201)
async def create_qa_pair(
    body: QAPairCreate,
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_KB)),
    db: AsyncSession = Depends(get_db),
):
    """创建 QA 对"""
    pair = await _qa_service.create_pair(
        db,
        current_user.tenant_id,
        question=body.question,
        answer=body.answer,
        keywords=body.keywords,
        employee_id=current_user.id,
    )
    return _to_response(pair)


@router.put("/{pair_id}", response_model=QAPairResponse)
async def update_qa_pair(
    pair_id: int,
    body: QAPairUpdate,
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_KB)),
    db: AsyncSession = Depends(get_db),
):
    """更新 QA 对"""
    pair = await _qa_service.update_pair(
        db,
        pair_id,
        current_user.tenant_id,
        question=body.question,
        answer=body.answer,
        keywords=body.keywords,
        is_active=body.is_active,
    )
    if not pair:
        raise HTTPException(status_code=404, detail="QA对不存在")
    return _to_response(pair)


@router.delete("/{pair_id}", status_code=204)
async def delete_qa_pair(
    pair_id: int,
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_KB)),
    db: AsyncSession = Depends(get_db),
):
    """删除 QA 对"""
    ok = await _qa_service.delete_pair(db, pair_id, current_user.tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="QA对不存在")
