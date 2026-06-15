"""租户权限码 API。平台管理员不使用租户 RBAC 权限列表。"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.database import get_db
from app.dependencies import require_tenant_user
from app.models.employee import Employee
from app.models.role import Permission, PermissionCode
from app.schemas.role import PermissionGroupedResponse, PermissionResponse

router = APIRouter(prefix="/permissions", tags=["权限"])

# 业务模块（租户管理员可见）
BUSINESS_MODULE_GROUPS = [
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
]

@router.get("", response_model=list[PermissionGroupedResponse])
async def list_permissions(
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_tenant_user),
):
    """获取租户可分配的业务权限码列表（按模块分组）。"""
    result = await db.execute(select(Permission))
    perms = result.scalars().all()
    perm_map: dict[str, PermissionResponse] = {
        p.code: PermissionResponse(id=p.id, code=p.code, name=p.name, description=p.description)
        for p in perms
    }

    # 租户管理员看不到平台专有权限模块
    module_groups = list(BUSINESS_MODULE_GROUPS)

    groups: list[PermissionGroupedResponse] = []
    for module_name, codes in module_groups:
        items = [perm_map[c.value] for c in codes if c.value in perm_map]
        if items:
            groups.append(PermissionGroupedResponse(module=module_name, permissions=items))

    return groups
