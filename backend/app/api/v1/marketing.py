"""营销资料 API — Phase 11"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.database import get_db
from app.dependencies import require_tenant_user
from app.models.employee import Employee
from app.schemas.marketing import (
    MarketingDocCreate,
    MarketingDocListResponse,
    MarketingDocResponse,
    MarketingDocUpdate,
)
from app.services.marketing_service import MarketingService

router = APIRouter(prefix="/marketing", tags=["营销资料"])

_marketing_service = MarketingService()


def _to_response(doc) -> MarketingDocResponse:
    return MarketingDocResponse(
        id=doc.id,
        title=doc.title,
        file_url=doc.file_url,
        file_type=doc.file_type,
        question_associations=doc.question_associations,
        is_active=doc.is_active,
        created_by_employee_id=doc.created_by_employee_id,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


@router.get("", response_model=MarketingDocListResponse)
async def list_marketing_docs(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    is_active: bool | None = None,
    current_user: Employee = Depends(require_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    """获取营销资料列表"""
    items, total = await _marketing_service.list_docs(
        db, current_user.tenant_id, skip, limit, is_active
    )
    return MarketingDocListResponse(
        items=[_to_response(item) for item in items],
        total=total,
    )


@router.post("", response_model=MarketingDocResponse, status_code=201)
async def create_marketing_doc(
    body: MarketingDocCreate,
    current_user: Employee = Depends(require_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    """创建营销资料"""
    doc = await _marketing_service.create_doc(
        db,
        current_user.tenant_id,
        title=body.title,
        file_url="",  # 上传文件后回填真实地址
        file_type=body.file_type,
        employee_id=current_user.id,
    )
    return _to_response(doc)


@router.put("/{doc_id}", response_model=MarketingDocResponse)
async def update_marketing_doc(
    doc_id: int,
    body: MarketingDocUpdate,
    current_user: Employee = Depends(require_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    """更新营销资料"""
    doc = await _marketing_service.update_doc(
        db,
        doc_id,
        current_user.tenant_id,
        title=body.title,
        file_type=body.file_type,
        question_associations=body.question_associations,
        is_active=body.is_active,
    )
    if not doc:
        raise HTTPException(status_code=404, detail="资料不存在")
    return _to_response(doc)


@router.delete("/{doc_id}", status_code=204)
async def delete_marketing_doc(
    doc_id: int,
    current_user: Employee = Depends(require_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    """删除营销资料"""
    ok = await _marketing_service.delete_doc(db, doc_id, current_user.tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="资料不存在")
