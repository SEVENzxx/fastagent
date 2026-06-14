"""分类管理服务。

提供租户级分类树的 CRUD 操作，支持多级嵌套分类和级联删除。
所有操作均强制传入 tenant_id 进行多租户隔离。
"""

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.product import Product


async def list_categories(db: AsyncSession, tenant_id: int) -> list[Category]:
    """查询当前租户的全部分类列表。

    按排序权重升序、创建时间升序排列，前端可按需构建分类树。

    参数：
        db: 异步数据库会话。
        tenant_id: 租户 ID（SaaS 多租户隔离必备）。

    返回：
        分类 ORM 对象列表。
    """
    result = await db.execute(
        select(Category)
        .where(Category.tenant_id == tenant_id)
        .order_by(Category.sort_order.asc(), Category.created_at.asc())
    )
    return list(result.scalars().all())


async def get_category(
    db: AsyncSession, category_id: int, tenant_id: int
) -> Category | None:
    """按 ID 获取当前租户下的单个分类。

    参数：
        db: 异步数据库会话。
        category_id: 分类 ID。
        tenant_id: 租户 ID。

    返回：
        分类对象，不存在则返回 None。
    """
    return await db.scalar(
        select(Category).where(
            Category.id == category_id,
            Category.tenant_id == tenant_id,
        )
    )


async def create_category(
    db: AsyncSession,
    tenant_id: int,
    name: str,
    parent_id: int | None,
    sort_order: int,
) -> Category:
    """在租户下创建新分类。

    支持指定父分类建立层级关系，会校验父分类确实属于当前租户。
    名称首尾空格会被自动清理。

    参数：
        db: 异步数据库会话。
        tenant_id: 租户 ID。
        name: 分类名称。
        parent_id: 父分类 ID，None 表示根分类。
        sort_order: 排序权重。

    返回：
        新创建的 Category ORM 对象。

    异常：
        ValueError: 名称为空或父分类不存在。
    """
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("分类名称不能为空")

    if parent_id is not None:
        parent = await get_category(db, parent_id, tenant_id)
        if parent is None:
            raise ValueError("父分类不存在")

    category = Category(
        tenant_id=tenant_id,
        name=clean_name,
        parent_id=parent_id,
        sort_order=sort_order,
    )
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return category


async def _is_descendant(
    db: AsyncSession,
    tenant_id: int,
    ancestor_id: int,
    candidate_id: int,
) -> bool:
    """检查 candidate_id 是否是 ancestor_id 的后代节点。

    通过沿 parent_id 链向上逐级查找，用于防止分类移动操作形成循环引用。

    参数：
        db: 异步数据库会话。
        tenant_id: 租户 ID。
        ancestor_id: 候选祖先节点 ID。
        candidate_id: 候选后代节点 ID。

    返回：
        若 candidate 是 ancestor 的后代则为 True。
    """
    current = await get_category(db, candidate_id, tenant_id)
    while current is not None and current.parent_id is not None:
        if current.parent_id == ancestor_id:
            return True
        current = await get_category(db, current.parent_id, tenant_id)
    return False


async def update_category(
    db: AsyncSession,
    category_id: int,
    tenant_id: int,
    *,
    name: str | None = None,
    parent_id: int | None = None,
    parent_id_provided: bool = False,
    sort_order: int | None = None,
) -> Category | None:
    """部分更新分类信息。

    支持修改名称、父分类、排序权重；移动分类时会校验不形成循环引用。
    parent_id_provided 字段用于区分「不修改父分类」和「显式设为 None（提升为根分类）」。

    参数：
        db: 异步数据库会话。
        category_id: 要更新的分类 ID。
        tenant_id: 租户 ID。
        name: 新名称（可选）。
        parent_id: 新父分类 ID，None 表示根分类（仅当 parent_id_provided=True 时生效）。
        parent_id_provided: 是否显式提供了父分类参数。
        sort_order: 新排序权重（可选）。

    返回：
        更新后的分类对象，分类不存在则返回 None。

    异常：
        ValueError: 名称空、父分类不存在、不能设为自己或后代。
    """
    category = await get_category(db, category_id, tenant_id)
    if category is None:
        return None

    if name is not None:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("分类名称不能为空")
        category.name = clean_name

    if parent_id_provided:
        if parent_id == category_id:
            raise ValueError("不能将分类设为自己的子分类")
        if parent_id is not None:
            parent = await get_category(db, parent_id, tenant_id)
            if parent is None:
                raise ValueError("父分类不存在")
            if await _is_descendant(db, tenant_id, category_id, parent_id):
                raise ValueError("不能将分类移动到自己的下级分类")
        category.parent_id = parent_id

    if sort_order is not None:
        category.sort_order = sort_order

    await db.commit()
    await db.refresh(category)
    return category


async def delete_category(db: AsyncSession, category_id: int, tenant_id: int) -> bool:
    """级联删除分类及其所有子分类。

    删除前会收集所有后代节点（DFS 遍历），将该分类树下所有关联商品的
    category_id 置为 None，再统一删除分类记录。保证 SaaS 数据不会因分类
    删除而产生数据不一致。

    参数：
        db: 异步数据库会话。
        category_id: 要删除的分类 ID。
        tenant_id: 租户 ID。

    返回：
        成功删除返回 True，分类不存在返回 False。
    """
    category = await get_category(db, category_id, tenant_id)
    if category is None:
        return False

    descendant_ids = _collect_descendant_ids(await list_categories(db, tenant_id), category_id)
    target_ids = [category_id, *descendant_ids]
    await db.execute(
        update(Product)
        .where(Product.tenant_id == tenant_id, Product.category_id.in_(target_ids))
        .values(category_id=None)
    )
    await db.execute(
        delete(Category).where(
            Category.tenant_id == tenant_id,
            Category.id.in_(target_ids),
        )
    )
    await db.commit()
    return True


def _collect_descendant_ids(categories: list[Category], category_id: int) -> list[int]:
    """通过 DFS 收集指定分类的所有后代节点 ID。

    先在内存中按 parent_id 分组构建邻接表，再从目标节点出发做深度优先搜索。
    纯内存计算，不产生数据库 IO。

    参数：
        categories: 租户下全部分类列表。
        category_id: 目标分类 ID。

    返回：
        所有后代分类的 ID 列表（不含自身）。
    """
    children_by_parent: dict[int, list[Category]] = {}
    for category in categories:
        if category.parent_id is not None:
            children_by_parent.setdefault(category.parent_id, []).append(category)

    result: list[int] = []
    stack = list(children_by_parent.get(category_id, []))
    while stack:
        node = stack.pop()
        result.append(node.id)
        stack.extend(children_by_parent.get(node.id, []))
    return result


def build_category_tree(categories: list[Category]) -> list[dict]:
    """将扁平分类列表构建为树形结构。

    前端分类选择器和树形展示依赖此函数将 DB 平铺数据转为嵌套 JSON。
    纯函数，不涉及数据库操作，可安全在渲染路径中调用。

    参数：
        categories: 租户下全部分类列表。

    返回：
        树形节点列表，每个节点含 id、name、parent_id、children 等字段。
    """
    nodes = {
        category.id: {
            "id": category.id,
            "tenant_id": category.tenant_id,
            "parent_id": category.parent_id,
            "name": category.name,
            "sort_order": category.sort_order,
            "created_at": category.created_at,
            "children": [],
        }
        for category in categories
    }

    roots: list[dict] = []
    for category in categories:
        node = nodes[category.id]
        if category.parent_id is not None and category.parent_id in nodes:
            nodes[category.parent_id]["children"].append(node)
        else:
            roots.append(node)

    return roots
