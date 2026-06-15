"""渠道配置 API。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.database import get_db
from app.dependencies import require_permission
from app.models.employee import Employee
from app.models.platform import Platform
from app.models.role import PermissionCode
from app.schemas.platform import PlatformCreate, PlatformListResponse, PlatformResponse, PlatformUpdate
from app.services import platform_service

router = APIRouter(prefix="/platforms", tags=["渠道配置"])


def _to_response(platform: Platform) -> PlatformResponse:
    return PlatformResponse(
        id=platform.id,
        tenant_id=platform.tenant_id,
        type=platform.type,
        name=platform.name,
        config=platform.config or {},
        webhook_url=platform.webhook_url,
        is_active=platform.is_active,
        created_at=platform.created_at,
    )


@router.get("", response_model=PlatformListResponse)
async def list_platforms(
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.VIEW_CHANNELS)),
):
    items, total = await platform_service.list_platforms(db, current_user.tenant_id)
    return PlatformListResponse(items=[_to_response(item) for item in items], total=total)


@router.post("", response_model=PlatformResponse, status_code=status.HTTP_201_CREATED)
async def create_platform(
    body: PlatformCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_CHANNELS)),
):
    try:
        platform = await platform_service.create_platform(db, current_user.tenant_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _to_response(platform)


@router.get("/{platform_id}", response_model=PlatformResponse)
async def get_platform(
    platform_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.VIEW_CHANNELS)),
):
    platform = await platform_service.get_platform(db, platform_id, current_user.tenant_id)
    if platform is None:
        raise HTTPException(status_code=404, detail="渠道不存在")
    return _to_response(platform)


@router.put("/{platform_id}", response_model=PlatformResponse)
async def update_platform(
    platform_id: int,
    body: PlatformUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_CHANNELS)),
):
    platform = await platform_service.update_platform(
        db,
        platform_id,
        current_user.tenant_id,
        body,
    )
    if platform is None:
        raise HTTPException(status_code=404, detail="渠道不存在")
    return _to_response(platform)


@router.delete("/{platform_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_platform(
    platform_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_CHANNELS)),
):
    ok = await platform_service.delete_platform(db, platform_id, current_user.tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="渠道不存在")
