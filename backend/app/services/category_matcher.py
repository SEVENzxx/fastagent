"""租户分类匹配工具模块。

提供基于租户自有分类树的叶子节点匹配能力，用于将 AI 提取的商品属性
映射到租户实际配置的分类体系，不依赖平台级行业别名。
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category


def leaf_categories(categories: Iterable[Category]) -> list[Category]:
    """从给定分类集合中筛选出所有叶子节点（没有子分类的节点）。

    遍历传入的分类列表，收集所有被其他分类引用的 parent_id，
    然后排除这些「被作为父节点」的分类，剩下的就是叶子分类。

    Args:
        categories: 租户下的全部或部分分类集合。

    Returns:
        叶子分类列表。
    """
    items = list(categories)
    # 收集所有作为父分类引用的 id
    parent_ids = {category.parent_id for category in items if category.parent_id is not None}
    # 排除父节点，保留叶子节点
    return [category for category in items if category.id not in parent_ids]


def match_leaf_category_from_list(categories: Iterable[Category], candidates: Iterable[str | None]) -> Category | None:
    """在给定分类集合的叶子节点中，按候选文本进行匹配。

    匹配策略（由精确到模糊，两级优先级）：
    1. 精确匹配：候选文本与叶子分类名称完全相等。
    2. 子串匹配：叶子分类名称是候选文本的子串。

    匹配完全由租户数据驱动，不使用平台级行业别名。

    Args:
        categories: 租户下的分类集合。
        candidates: 待匹配的候选文本列表（可能包含 None）。

    Returns:
        匹配到的第一个叶子分类；未命中返回 None。
    """
    # 取叶子节点，按名称长度降序排列（长名称优先匹配，避免短名称误命中）
    leaves = sorted(leaf_categories(categories), key=lambda item: len(item.name or ""), reverse=True)
    # 清洗候选文本：去 None、去空、去首尾空格
    clean_candidates = [str(candidate).strip() for candidate in candidates if candidate and str(candidate).strip()]
    if not leaves or not clean_candidates:
        return None

    # 第一轮：精确匹配（候选文本 == 分类名称）
    for candidate in clean_candidates:
        for category in leaves:
            if category.name == candidate:
                return category

    # 第二轮：子串匹配（分类名称 in 候选文本）
    for candidate in clean_candidates:
        for category in leaves:
            if category.name and category.name in candidate:
                return category

    return None


async def get_tenant_leaf_categories(db: AsyncSession, tenant_id: int) -> list[Category]:
    """获取指定租户下的所有叶子分类。

    从数据库查询租户的全部分类后，过滤出叶子节点返回。

    Args:
        db: 异步数据库会话。
        tenant_id: 租户 ID。

    Returns:
        该租户的叶子分类列表。
    """
    result = await db.execute(select(Category).where(Category.tenant_id == tenant_id))
    return leaf_categories(result.scalars().all())


async def match_tenant_leaf_category(
    db: AsyncSession,
    tenant_id: int,
    candidates: Iterable[str | None],
) -> Category | None:
    """在指定租户的分类体系中，按候选文本匹配叶子分类。

    先查库获取租户全部分类，再在叶子节点中按精确→子串两级策略匹配。

    Args:
        db: 异步数据库会话。
        tenant_id: 租户 ID。
        candidates: 待匹配的候选文本列表（可能包含 None）。

    Returns:
        匹配到的叶子分类；未命中返回 None。
    """
    result = await db.execute(select(Category).where(Category.tenant_id == tenant_id))
    return match_leaf_category_from_list(result.scalars().all(), candidates)
