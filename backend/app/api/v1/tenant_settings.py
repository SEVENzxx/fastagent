"""Tenant self-service settings API."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.database import get_db
from app.dependencies import require_permission, require_tenant_user
from app.models.category import Category
from app.models.employee import Employee
from app.models.role import PermissionCode
from app.models.tenant import Tenant
from app.schemas.tenant import (
    CategoryAttrOption,
    TenantTemplateResponse,
    TenantTemplateUpdate,
)
from app.services.tenant_template import (
    get_category_attr_counts,
    get_tenant_attributes,
    normalize_template_to_attributes,
    update_tenant_template,
)

router = APIRouter(prefix="/tenant", tags=["租户设置"])


@router.get("/template", response_model=TenantTemplateResponse)
async def get_template(
    category_id: str = Query(default="", description="分类 ID，空表示未分类"),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_tenant_user),
):
    """获取当前租户指定分类的商品属性配置 Schema。"""
    attrs = await get_tenant_attributes(db, current_user.tenant_id, category_id)

    category_name = ""
    if category_id:
        cat = await db.get(Category, int(category_id))
        if cat and cat.tenant_id == current_user.tenant_id:
            category_name = cat.name

    return TenantTemplateResponse(
        category_id=category_id,
        category_name=category_name,
        attributes=attrs,
    )


@router.put("/template", response_model=TenantTemplateResponse)
async def update_template(
    body: TenantTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_PRODUCTS)),
):
    """更新租户指定分类的商品属性配置 Schema。"""
    # 校验分类存在
    if body.category_id:
        cat = await db.get(Category, int(body.category_id))
        if not cat or cat.tenant_id != current_user.tenant_id:
            raise HTTPException(status_code=404, detail="分类不存在")
        category_name = cat.name
    else:
        category_name = "未分类"

    try:
        attrs = await update_tenant_template(
            db, current_user.tenant_id, body.category_id, body.attributes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return TenantTemplateResponse(
        category_id=body.category_id,
        category_name=category_name,
        attributes=attrs,
    )


@router.get("/template/categories", response_model=list[CategoryAttrOption])
async def list_template_categories(
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_tenant_user),
):
    """获取已有属性配置的分类选项列表。"""
    value = await db.scalar(
        select(Tenant.template_json).where(Tenant.id == current_user.tenant_id)
    )
    counts = get_category_attr_counts(value)

    result: list[CategoryAttrOption] = []
    for cid_str, count in counts.items():
        if not cid_str:
            result.append(CategoryAttrOption(
                category_id="",
                category_name="未分类",
                attr_count=count,
            ))
            continue
        try:
            cat = await db.get(Category, int(cid_str))
            if cat and cat.tenant_id == current_user.tenant_id:
                result.append(CategoryAttrOption(
                    category_id=cid_str,
                    category_name=cat.name,
                    attr_count=count,
                ))
        except (ValueError, TypeError):
            pass

    return result
