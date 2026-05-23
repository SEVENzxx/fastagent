"""联系人管理 API"""

import io

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_permission
from app.models.contact import Contact
from app.models.employee import Employee
from app.models.role import PermissionCode
from app.schemas.contact import (
    ContactAssign,
    ContactCreate,
    ContactImportResponse,
    ContactListResponse,
    ContactResponse,
    ContactTagAggregate,
    ContactUpdate,
)
from app.services import contact_service

router = APIRouter(prefix="/contacts", tags=["联系人"])


def _to_response(contact: Contact) -> ContactResponse:
    return ContactResponse(
        id=contact.id,
        tenant_id=contact.tenant_id,
        name=contact.name,
        avatar_url=contact.avatar_url,
        phone=contact.phone,
        address=contact.address,
        external_ids=contact.external_ids or {},
        tags=contact.tags or [],
        merged_from=contact.merged_from,
        assigned_employee_id=contact.assigned_employee_id,
        assigned_employee_name=getattr(contact, "_assigned_employee_name", None),
        created_at=contact.created_at,
        updated_at=contact.updated_at,
    )


@router.get("", response_model=ContactListResponse)
async def list_contacts(
    keyword: str = Query(default=""),
    tag: str | None = Query(default=None),
    assigned_employee_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.VIEW_CONTACTS)),
):
    items, total = await contact_service.list_contacts(
        db,
        current_user.tenant_id,
        keyword=keyword,
        tag=tag,
        assigned_employee_id=assigned_employee_id,
        page=page,
        page_size=page_size,
    )
    return ContactListResponse(
        items=[_to_response(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/import/template")
async def download_import_template(
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_CONTACTS)),
):
    """下载联系人批量导入 CSV 模板"""
    _ = current_user
    return StreamingResponse(
        io.BytesIO(contact_service.CONTACT_IMPORT_TEMPLATE.encode("utf-8-sig")),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="contact_import_template.csv"'
        },
    )


@router.post("/import", response_model=ContactImportResponse)
async def import_contacts(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_CONTACTS)),
):
    """批量导入联系人 CSV"""
    filename = file.filename or ""
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="请上传 CSV 文件")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="CSV 文件不能超过 2MB")

    try:
        return await contact_service.import_contacts_csv(
            db,
            current_user.tenant_id,
            content,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/tags", response_model=list[ContactTagAggregate])
async def get_contact_tags(
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.VIEW_CONTACTS)),
):
    tags = await contact_service.aggregate_tags(db, current_user.tenant_id)
    return [ContactTagAggregate(tag=tag, count=count) for tag, count in tags]


@router.get("/{contact_id}", response_model=ContactResponse)
async def get_contact(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.VIEW_CONTACTS)),
):
    contact = await contact_service.get_contact(db, contact_id, current_user.tenant_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="联系人不存在")
    return _to_response(contact)


@router.post("", response_model=ContactResponse, status_code=status.HTTP_201_CREATED)
async def create_contact(
    body: ContactCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_CONTACTS)),
):
    try:
        contact = await contact_service.create_contact(db, current_user.tenant_id, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_response(contact)


@router.put("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: int,
    body: ContactUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_CONTACTS)),
):
    try:
        contact = await contact_service.update_contact(
            db,
            contact_id,
            current_user.tenant_id,
            body,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if contact is None:
        raise HTTPException(status_code=404, detail="联系人不存在")
    return _to_response(contact)


@router.put("/{contact_id}/assign", response_model=ContactResponse)
async def assign_contact(
    contact_id: int,
    body: ContactAssign,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_CONTACTS)),
):
    try:
        contact = await contact_service.assign_contact(
            db,
            contact_id,
            current_user.tenant_id,
            body,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if contact is None:
        raise HTTPException(status_code=404, detail="联系人不存在")
    return _to_response(contact)


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_CONTACTS)),
):
    ok = await contact_service.delete_contact(db, contact_id, current_user.tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="联系人不存在")
