"""Tenant self-service settings API."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.database import get_db
from app.dependencies import require_permission, require_tenant_user
from app.models.employee import Employee
from app.models.role import PermissionCode
from app.schemas.tenant import TenantTemplateResponse, TenantTemplateUpdate
from app.services.tenant_template import get_tenant_template, update_tenant_template

router = APIRouter(prefix="/tenant", tags=["租户设置"])


@router.get("/template", response_model=TenantTemplateResponse)
async def get_template(
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_tenant_user),
):
    return TenantTemplateResponse(
        template_json=await get_tenant_template(db, current_user.tenant_id)
    )


@router.put("/template", response_model=TenantTemplateResponse)
async def update_template(
    body: TenantTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_PRODUCTS)),
):
    try:
        template = await update_tenant_template(db, current_user.tenant_id, body.template_json)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TenantTemplateResponse(template_json=template)
