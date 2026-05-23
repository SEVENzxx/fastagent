"""分类管理 API"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_permission
from app.models.employee import Employee
from app.models.role import PermissionCode
from app.schemas.category import (
    CategoryCreate,
    CategoryResponse,
    CategoryTreeResponse,
    CategoryUpdate,
)
from app.services import category_service

router = APIRouter(prefix="/categories", tags=["分类"])


def _to_response(cat) -> CategoryResponse:
    return CategoryResponse(
        id=cat.id,
        tenant_id=cat.tenant_id,
        parent_id=cat.parent_id,
        name=cat.name,
        sort_order=cat.sort_order,
        created_at=cat.created_at,
    )


def _to_tree_node(node: dict) -> CategoryTreeResponse:
    return CategoryTreeResponse(
        id=node["id"],
        tenant_id=node["tenant_id"],
        parent_id=node["parent_id"],
        name=node["name"],
        sort_order=node["sort_order"],
        created_at=node["created_at"],
        children=[_to_tree_node(child) for child in node["children"]],
    )


@router.get("", response_model=list[CategoryResponse])
async def list_categories(
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """获取所有分类（平铺列表）"""
    cats = await category_service.list_categories(db, current_user.tenant_id)
    return [_to_response(c) for c in cats]


@router.get("/tree", response_model=list[CategoryTreeResponse])
async def get_category_tree(
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """获取分类树"""
    cats = await category_service.list_categories(db, current_user.tenant_id)
    tree = category_service.build_category_tree(cats)
    return [_to_tree_node(node) for node in tree]


@router.get("/{category_id}", response_model=CategoryResponse)
async def get_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """获取单个分类"""
    cat = await category_service.get_category(db, category_id, current_user.tenant_id)
    if not cat:
        raise HTTPException(status_code=404, detail="分类不存在")
    return _to_response(cat)


@router.post("", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    body: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_PRODUCTS)),
):
    """创建分类"""
    try:
        cat = await category_service.create_category(
            db,
            current_user.tenant_id,
            body.name,
            body.parent_id,
            body.sort_order,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_response(cat)


@router.put("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: int,
    body: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_PRODUCTS)),
):
    """更新分类"""
    try:
        cat = await category_service.update_category(
            db,
            category_id,
            current_user.tenant_id,
            name=body.name,
            parent_id=body.parent_id,
            parent_id_provided="parent_id" in body.model_fields_set,
            sort_order=body.sort_order,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not cat:
        raise HTTPException(status_code=404, detail="分类不存在")
    return _to_response(cat)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_PRODUCTS)),
):
    """删除分类（级联删除子分类）"""
    ok = await category_service.delete_category(db, category_id, current_user.tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="分类不存在")
