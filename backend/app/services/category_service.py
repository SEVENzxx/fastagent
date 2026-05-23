"""Category management service."""

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.product import Product


async def list_categories(db: AsyncSession, tenant_id: int) -> list[Category]:
    result = await db.execute(
        select(Category)
        .where(Category.tenant_id == tenant_id)
        .order_by(Category.sort_order.asc(), Category.created_at.asc())
    )
    return list(result.scalars().all())


async def get_category(
    db: AsyncSession, category_id: int, tenant_id: int
) -> Category | None:
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
