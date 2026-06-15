"""图片库 API — Phase 11"""

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.database import get_db
from app.dependencies import require_tenant_user
from app.models.employee import Employee
from app.schemas.image import ImageListResponse, ImageResponse, ImageUpdate
from app.services.image_service import ImageService

router = APIRouter(prefix="/images", tags=["图片库"])

_image_service = ImageService()


def _to_response(img) -> ImageResponse:
    return ImageResponse(
        id=img.id,
        filename=img.filename,
        storage_path=img.storage_path,
        file_url=img.file_url,
        file_size=img.file_size,
        mime_type=img.mime_type,
        width=img.width,
        height=img.height,
        product_id=img.product_id,
        tags=img.tags,
        created_by_employee_id=img.created_by_employee_id,
        created_at=img.created_at,
        updated_at=img.updated_at,
    )


@router.get("", response_model=ImageListResponse)
async def list_images(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    product_id: int | None = None,
    current_user: Employee = Depends(require_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    """获取图片列表"""
    items, total = await _image_service.list_images(
        db, current_user.tenant_id, skip, limit, product_id
    )
    return ImageListResponse(
        items=[_to_response(item) for item in items],
        total=total,
    )


@router.post("/upload", response_model=ImageResponse, status_code=201)
async def upload_image(
    file: UploadFile = File(...),
    current_user: Employee = Depends(require_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    """上传图片"""
    image = await _image_service.upload_image(
        db, file, current_user.tenant_id, current_user.id
    )
    return _to_response(image)


@router.put("/{image_id}", response_model=ImageResponse)
async def update_image(
    image_id: int,
    body: ImageUpdate,
    current_user: Employee = Depends(require_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    """更新图片信息"""
    image = await _image_service.update_image(
        db, image_id, current_user.tenant_id,
        tags=body.tags, product_id=body.product_id,
    )
    if not image:
        raise HTTPException(status_code=404, detail="图片不存在")
    return _to_response(image)


@router.delete("/{image_id}", status_code=204)
async def delete_image(
    image_id: int,
    current_user: Employee = Depends(require_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    """删除图片"""
    ok = await _image_service.delete_image(db, image_id, current_user.tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="图片不存在")
