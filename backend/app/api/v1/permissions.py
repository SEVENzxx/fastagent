"""权限码 API"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.role import Permission, PermissionCode
from app.schemas.role import PermissionGroupedResponse, PermissionResponse

router = APIRouter(prefix="/permissions", tags=["权限"])

MODULE_GROUPS = [
    ("会话", [
        PermissionCode.VIEW_ASSIGNED_CHATS, PermissionCode.VIEW_ALL_CHATS,
        PermissionCode.MANAGE_CONVERSATIONS,
    ]),
    ("客户", [
        PermissionCode.VIEW_CONTACTS, PermissionCode.MANAGE_CONTACTS,
        PermissionCode.EXPORT_CONTACTS,
    ]),
    ("商品", [
        PermissionCode.VIEW_PRODUCTS, PermissionCode.MANAGE_PRODUCTS,
    ]),
    ("订单", [
        PermissionCode.VIEW_ORDERS, PermissionCode.MANAGE_ORDERS,
        PermissionCode.UPDATE_ORDER_STATUS,
    ]),
    ("知识库", [
        PermissionCode.VIEW_KB, PermissionCode.MANAGE_KB,
    ]),
    ("营销资料", [
        PermissionCode.VIEW_MARKETING, PermissionCode.MANAGE_MARKETING,
    ]),
    ("图片库", [
        PermissionCode.VIEW_IMAGES, PermissionCode.MANAGE_IMAGES,
    ]),
    ("员工/团队", [
        PermissionCode.VIEW_EMPLOYEES, PermissionCode.MANAGE_EMPLOYEES,
        PermissionCode.MANAGE_ROLES,
    ]),
    ("计费与用量", [
        PermissionCode.VIEW_BILLING, PermissionCode.MANAGE_BILLING,
    ]),
    ("数据分析", [
        PermissionCode.VIEW_ANALYTICS, PermissionCode.EXPORT_ANALYTICS,
    ]),
    ("渠道", [
        PermissionCode.VIEW_CHANNELS, PermissionCode.MANAGE_CHANNELS,
    ]),
    ("LLM与AI", [
        PermissionCode.MANAGE_LLM_CONFIG, PermissionCode.MANAGE_SENSITIVE_WORDS,
    ]),
    ("系统管理", [
        PermissionCode.MANAGE_TENANTS, PermissionCode.MANAGE_PLANS,
        PermissionCode.VIEW_AUDIT_LOGS, PermissionCode.MANAGE_BACKUPS,
        PermissionCode.MANAGE_SYSTEM_SETTINGS, PermissionCode.EXPORT_DATA,
    ]),
]


@router.get("", response_model=list[PermissionGroupedResponse])
async def list_permissions(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """获取系统全部权限码（按模块分组）。任何已登录用户可访问。"""
    result = await db.execute(select(Permission))
    perms = result.scalars().all()
    perm_map: dict[str, PermissionResponse] = {
        p.code: PermissionResponse(id=p.id, code=p.code, name=p.name, description=p.description)
        for p in perms
    }

    groups: list[PermissionGroupedResponse] = []
    for module_name, codes in MODULE_GROUPS:
        items = [perm_map[c.value] for c in codes if c.value in perm_map]
        if items:
            groups.append(PermissionGroupedResponse(module=module_name, permissions=items))

    return groups
