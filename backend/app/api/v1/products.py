"""商品管理 API"""

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import io

from app.database import get_db
from app.dependencies import require_permission, require_tenant_user
from app.models.employee import Employee
from app.models.role import PermissionCode
from app.schemas.product import (
    ProductCreate,
    ProductImportResponse,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
)
from app.services import product_service

router = APIRouter(prefix="/products", tags=["商品"])


def _to_response(product) -> ProductResponse:
    return ProductResponse(
        id=product.id,
        tenant_id=product.tenant_id,
        category_id=product.category_id,
        name=product.name,
        sku=product.sku,
        description=product.description,
        price=float(product.price) if product.price is not None else None,
        floor_price=float(product.floor_price) if product.floor_price is not None else None,
        stock=product.stock,
        is_sample=product.is_sample,
        sales_template_id=product.sales_template_id,
        specs=product.specs,
        is_active=product.is_active,
        created_at=product.created_at,
        updated_at=product.updated_at,
        category_name=getattr(product, "_category_name", None),
        attrs_json=product.attrs_json,
        feature_tags=product.feature_tags or [],
        scenario_tags=product.scenario_tags or [],
    )


@router.get("/search", response_model=ProductListResponse)
async def search_products(
    keyword: str = Query(default=""),
    category_id: int | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    is_sample: bool | None = Query(default=None),
    min_price: float | None = Query(default=None),
    max_price: float | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_tenant_user),
):
    """搜索/筛选商品"""
    items, total = await product_service.list_products(
        db,
        current_user.tenant_id,
        keyword=keyword,
        category_id=category_id,
        is_active=is_active,
        is_sample=is_sample,
        min_price=min_price,
        max_price=max_price,
        page=page,
        page_size=page_size,
    )
    return ProductListResponse(
        items=[_to_response(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("", response_model=ProductListResponse)
async def list_products(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_tenant_user),
):
    """获取商品列表"""
    items, total = await product_service.list_products(
        db,
        current_user.tenant_id,
        page=page,
        page_size=page_size,
    )
    return ProductListResponse(
        items=[_to_response(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/import/template")
async def download_import_template(
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_PRODUCTS)),
):
    """下载商品批量导入 CSV 模板"""
    _ = current_user
    return StreamingResponse(
        io.BytesIO(product_service.PRODUCT_IMPORT_TEMPLATE.encode("utf-8-sig")),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="product_import_template.csv"'
        },
    )


@router.post("/import", response_model=ProductImportResponse)
async def import_products(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_PRODUCTS)),
):
    """批量导入商品 CSV"""
    filename = file.filename or ""
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="请上传 CSV 文件")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="CSV 文件不能超过 2MB")

    try:
        return await product_service.import_products_csv(
            db,
            current_user.tenant_id,
            content,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_tenant_user),
):
    """获取单个商品"""
    product = await product_service.get_product(db, product_id, current_user.tenant_id)
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    return _to_response(product)


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    body: ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_PRODUCTS)),
):
    """创建商品"""
    try:
        product = await product_service.create_product(
            db, current_user.tenant_id, body
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_response(product)


@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    body: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_PRODUCTS)),
):
    """更新商品"""
    try:
        product = await product_service.update_product(
            db, product_id, current_user.tenant_id, body
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    return _to_response(product)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_PRODUCTS)),
):
    """删除商品"""
    ok = await product_service.delete_product(db, product_id, current_user.tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="商品不存在")
