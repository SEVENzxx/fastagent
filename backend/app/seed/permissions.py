"""种子数据 —— 权限码初始化"""

import asyncio

from sqlalchemy import select

from app.integrations.database import AsyncSessionLocal
from app.models.role import Permission, PermissionCode


PERMISSIONS_DATA = [
    # ── 会话 ──
    ("view_assigned_chats", "查看已分配会话", "查看分配给自己的会话列表"),
    ("view_all_chats", "查看全部会话", "查看租户内所有会话（主管/管理员）"),
    ("manage_conversations", "管理会话", "分配、关闭、转接会话"),
    # ── 客户/联系人 ──
    ("view_contacts", "查看联系人", "查看联系人列表和详情"),
    ("manage_contacts", "管理联系人", "创建、编辑、删除联系人"),
    ("export_contacts", "导出联系人", "导出联系人数据为CSV"),
    # ── 商品 ──
    ("view_products", "查看商品", "查看商品列表和详情"),
    ("manage_products", "管理商品", "创建、编辑、删除商品"),
    # ── 订单 ──
    ("view_orders", "查看订单", "查看订单列表和详情"),
    ("manage_orders", "管理订单", "创建、编辑订单"),
    ("update_order_status", "更新订单状态", "变更订单状态（确认/发货/完成/取消）"),
    # ── 知识库 ──
    ("view_kb", "查看知识库", "查看知识库文档和问答对"),
    ("manage_kb", "管理知识库", "上传、编辑、删除知识库文档、问答对"),
    # ── 营销资料 ──
    ("view_marketing", "查看营销资料", "查看营销资料列表"),
    ("manage_marketing", "管理营销资料", "创建、编辑、删除营销资料"),
    # ── 图片库 ──
    ("view_images", "查看图片库", "查看图片库"),
    ("manage_images", "管理图片库", "上传、删除图片"),
    # ── 员工/团队 ──
    ("view_employees", "查看员工", "查看员工列表"),
    ("manage_employees", "管理员工", "创建、编辑、删除员工"),
    ("manage_roles", "管理角色", "创建、编辑、删除角色，分配权限"),
    # ── 计费与用量 ──
    ("view_billing", "查看计费", "查看账单和用量"),
    ("manage_billing", "管理计费", "生成账单、标记已付"),
    # ── 数据分析 ──
    ("view_analytics", "查看分析", "查看数据分析看板"),
    ("export_analytics", "导出分析", "导出分析报表为CSV"),
    # ── 渠道配置 ──
    ("view_channels", "查看渠道", "查看渠道配置"),
    ("manage_channels", "管理渠道", "创建、编辑渠道配置"),
    # ── LLM 与 AI ──
    ("manage_llm_config", "管理LLM配置", "管理LLM模型和API配置"),
    ("manage_sensitive_words", "管理敏感词", "管理敏感词库"),
    # ── Admin/超管 ──
    ("manage_tenants", "管理租户", "创建、编辑、删除租户（超管）"),
    ("manage_plans", "管理套餐", "创建、编辑套餐（超管）"),
    ("view_audit_logs", "查看审计日志", "查看操作审计日志（超管）"),
    ("manage_backups", "管理备份", "创建、下载、删除数据库备份（超管）"),
    ("manage_system_settings", "管理系统设置", "修改系统级设置（超管）"),
    ("export_data", "导出数据", "跨模块导出数据"),
]


async def seed_permissions() -> list[Permission]:
    """录入全部权限码（幂等：已存在的跳过）。返回所有权限对象列表。"""
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(select(Permission.code))).scalars().all()
        existing_codes = set(existing)

        created = []
        for code, name, description in PERMISSIONS_DATA:
            if code in existing_codes:
                continue
            perm = Permission(code=code, name=name, description=description)
            db.add(perm)
            created.append(perm)

        if created:
            await db.commit()

        all_perms = (await db.execute(select(Permission))).scalars().all()
        return list(all_perms)


async def main():
    perms = await seed_permissions()
    print(f"权限码已就绪，共 {len(perms)} 条")


if __name__ == "__main__":
    asyncio.run(main())
