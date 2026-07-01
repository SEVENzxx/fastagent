"""租户商品属性模板工具。

提供商品属性模板的规范化、校验和持久化能力。
按产品分类组织：{"category_attributes": {category_id: [AttributeDef, ...]}}
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.constants.config import TENANT_ATTR_CACHE_TTL
from app.integrations.redis_client import get_redis_client
from app.models.tenant import Tenant
from app.schemas.tenant import AttributeDef

logger = logging.getLogger(__name__)
ATTRS_JSON_EMPTY: dict[str, Any] = {"schema_version": 1, "attr": {}, "evidence": {}, "confidence": {}}

_CACHE_PREFIX = "tenant:attr"


# ──────────────────────────────────────
# template_json → AttributeDef 列表
# ──────────────────────────────────────


def normalize_template_to_attributes(
    value: object,
    category_id: str = "",
) -> list[AttributeDef]:
    """从 tenant.template_json 中提取指定分类的属性定义。

    新格式：{"category_attributes": {"123": [AttributeDef, ...], ...}}
    空 category_id 或分类无配置时返回空列表。
    """
    if value is None or not isinstance(value, dict):
        return []

    cat_attrs = value.get("category_attributes")
    if not isinstance(cat_attrs, dict):
        return []

    raw_attrs = cat_attrs.get(str(category_id))
    if not isinstance(raw_attrs, list):
        return []

    attrs: list[AttributeDef] = []
    seen_keys: set[str] = set()
    for item in raw_attrs:
        if not isinstance(item, dict):
            continue
        try:
            attr = AttributeDef(**item)
        except Exception:
            continue
        if attr.key in seen_keys:
            continue
        seen_keys.add(attr.key)
        attrs.append(attr)
    return attrs


def get_category_attr_counts(value: object) -> dict[str, int]:
    """获取所有分类的属性数量统计。"""
    if value is None or not isinstance(value, dict):
        return {}
    cat_attrs = value.get("category_attributes")
    if not isinstance(cat_attrs, dict):
        return {}
    return {
        cat_id: len(raw) if isinstance(raw, list) else 0
        for cat_id, raw in cat_attrs.items()
    }


# ──────────────────────────────────────
# attrs_json 规范化（按 Schema 过滤 + 补全）
# ──────────────────────────────────────


def normalize_attrs_json(
    value: object,
    attribute_defs: list[AttributeDef] | None = None,
) -> dict[str, dict[str, Any]]:
    """规范化商品属性 JSON，按租户属性定义过滤，强制输出 {"attr": {...}} 结构。

    未配置 attribute_defs 时不做过滤，仅确保输出结构。
    """
    allowed_keys: set[str] = set()
    key_to_def: dict[str, AttributeDef] = {}
    if attribute_defs:
        for ad in attribute_defs:
            allowed_keys.add(ad.key)
            key_to_def[ad.key] = ad

    if isinstance(value, dict) and isinstance(value.get("attr"), dict):
        raw_attr = value["attr"]
    elif isinstance(value, dict):
        raw_attr = value
    else:
        raw_attr = {}

    attr: dict[str, Any] = {}
    if isinstance(raw_attr, dict):
        for key, raw_value in raw_attr.items():
            field = str(key).strip()
            if not field:
                continue
            if attribute_defs is not None and field not in allowed_keys:
                continue

            ad = key_to_def.get(field)
            if ad:
                raw_value = _cast_by_type(raw_value, ad.type)

            if raw_value is None or isinstance(raw_value, (str, int, float, bool)):
                attr[field] = raw_value
            else:
                attr[field] = json.dumps(raw_value, ensure_ascii=False, sort_keys=True)

    # 补全 schema 中缺失的 key 为 null
    if attribute_defs:
        for ad in attribute_defs:
            if ad.key not in attr:
                attr[ad.key] = None

    return {"attr": attr}


def _cast_by_type(value: Any, attr_type: str) -> Any:
    """按属性类型强制转型。"""
    if value is None:
        return None
    if attr_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            v_lower = value.strip().lower()
            if v_lower in ("true", "yes", "1", "是"):
                return True
            if v_lower in ("false", "no", "0", "否", "不是"):
                return False
        return None
    if attr_type == "number":
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if attr_type == "text":
        return str(value).strip() if value is not None else None
    return value


# ──────────────────────────────────────
# 属性定义工具
# ──────────────────────────────────────


def build_schema_for_prompt(attribute_defs: list[AttributeDef]) -> list[dict[str, Any]]:
    """构建 LLM prompt 中使用的 schema JSON（精简版）。"""
    result: list[dict[str, Any]] = []
    for ad in attribute_defs:
        item: dict[str, Any] = {
            "key": ad.key,
            "label": ad.label,
            "type": ad.type,
        }
        if ad.aliases:
            item["aliases"] = ad.aliases
        if ad.description:
            item["description"] = ad.description
        if ad.unit:
            item["unit"] = ad.unit
        if ad.type == "enum" and ad.allowed_values:
            item["allowed_values"] = ad.allowed_values
        result.append(item)
    return result


# ──────────────────────────────────────
# 持久化服务
# ──────────────────────────────────────


async def get_tenant_attributes(
    db: AsyncSession,
    tenant_id: int,
    category_id: str = "",
) -> list[AttributeDef]:
    """查询租户指定分类的商品属性定义（Redis 缓存，24h TTL）。

    category_id 为空字符串时返回未分类商品的属性定义。
    """
    cache_key = f"{_CACHE_PREFIX}:{tenant_id}:{category_id or '_none'}"
    # 优先读 Redis
    attrs = await _read_attributes_from_cache(cache_key, category_id)
    if attrs is not None:
        return attrs

    # cache miss → 查 DB 并回写
    value = await db.scalar(select(Tenant.template_json).where(Tenant.id == tenant_id))
    attrs = normalize_template_to_attributes(value, category_id)
    await _write_attributes_to_cache(cache_key, value)
    return attrs


async def get_tenant_attributes_cached_only(tenant_id: int, category_id: str = "") -> list[AttributeDef] | None:
    """读取属性定义：Redis 优先，miss 时自动查 DB 兜底并回写缓存。"""
    cache_key = f"{_CACHE_PREFIX}:{tenant_id}:{category_id or '_none'}"
    attrs = await _read_attributes_from_cache(cache_key, category_id)
    if attrs is not None:
        return attrs

    # cache miss → 查 DB 兜底
    from app.integrations.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            value = await db.scalar(select(Tenant.template_json).where(Tenant.id == tenant_id))
            attrs = normalize_template_to_attributes(value, category_id)
            await _write_attributes_to_cache(cache_key, value)
            return attrs
    except Exception:
        logger.debug("属性定义 DB 查询失败: tenant_id=%s", tenant_id)
        return None


def normalize_all_attributes(value: object) -> list[AttributeDef]:
    """从 template_json 中提取所有分类的全部属性定义（去重）。"""
    if value is None or not isinstance(value, dict):
        return []

    cat_attrs = value.get("category_attributes")
    if not isinstance(cat_attrs, dict):
        return []

    seen_keys: set[str] = set()
    result: list[AttributeDef] = []
    for raw_list in cat_attrs.values():
        if not isinstance(raw_list, list):
            continue
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            try:
                attr = AttributeDef(**item)
            except Exception:
                continue
            if attr.key in seen_keys:
                continue
            seen_keys.add(attr.key)
            result.append(attr)
    return result


async def get_all_tenant_attributes_cached_only(tenant_id: int) -> list[AttributeDef] | None:
    """获取租户所有分类的全部属性定义（用于用户查询筛选场景）。

    筛选搜索时不知道用户要查哪个分类，需要列全让 LLM 判断。
    """
    cache_key = f"{_CACHE_PREFIX}:{tenant_id}:__all__"
    try:
        r = get_redis_client()
        cached = await r.get(cache_key)
        if cached:
            raw = json.loads(cached)
            if isinstance(raw, list):
                return [AttributeDef(**item) for item in raw if isinstance(item, dict)]
    except Exception:
        pass

    # cache miss → 查 DB
    from app.integrations.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            value = await db.scalar(select(Tenant.template_json).where(Tenant.id == tenant_id))
            attrs = normalize_all_attributes(value)
            # 回写缓存
            try:
                r = get_redis_client()
                await r.set(
                    cache_key,
                    json.dumps([ad.model_dump() for ad in attrs], ensure_ascii=False),
                    ex=TENANT_ATTR_CACHE_TTL,
                )
            except Exception:
                pass
            return attrs
    except Exception:
        logger.debug("全量属性定义 DB 查询失败: tenant_id=%s", tenant_id)
        return None


async def _read_attributes_from_cache(cache_key: str, category_id: str = "") -> list[AttributeDef] | None:
    """从 Redis 读取并范化属性定义。"""
    try:
        r = get_redis_client()
        cached = await r.get(cache_key)
        if cached:
            raw = json.loads(cached)
            # 缓存中可能存的是完整 template_json → 按分类提取
            if isinstance(raw, dict) and "category_attributes" in raw:
                attrs = normalize_template_to_attributes(raw, category_id)
                return attrs if attrs else []
            # 兼容：直接是属性列表
            if isinstance(raw, list):
                return [AttributeDef(**item) for item in raw if isinstance(item, dict)]
    except Exception:
        logger.debug("Redis 读取租户属性缓存失败: key=%s", cache_key)
    return None


async def _write_attributes_to_cache(cache_key: str, value: object) -> None:
    try:
        r = get_redis_client()
        await r.set(cache_key, json.dumps(value, ensure_ascii=False), ex=TENANT_ATTR_CACHE_TTL)
    except Exception:
        logger.debug("Redis 写入租户属性缓存失败: key=%s", cache_key)


async def update_tenant_template(
    db: AsyncSession,
    tenant_id: int,
    category_id: str,
    attributes: list[AttributeDef],
) -> list[AttributeDef]:
    """更新租户指定分类的商品属性模板，同时刷新 Redis 缓存。"""
    seen_keys: set[str] = set()
    validated: list[AttributeDef] = []
    for ad in attributes:
        if ad.key in seen_keys:
            continue
        seen_keys.add(ad.key)
        validated.append(ad)

    tenant = await db.get(Tenant, tenant_id)
    if tenant is None or tenant.deleted_at is not None:
        raise ValueError("租户不存在")

    # 读取现有 template_json，合并更新
    current = tenant.template_json or {}
    if not isinstance(current, dict):
        current = {}

    # ⚠️ 必须拷贝一份，不能原地修改 SQLAlchemy 已加载的 dict，
    # 否则 flush 时新旧值比较会认为没变化，不发出 UPDATE
    cat_attrs = dict(current.get("category_attributes") or {})
    cat_attrs[str(category_id)] = [ad.model_dump() for ad in validated]

    template_value = {"category_attributes": cat_attrs}
    tenant.template_json = template_value
    await db.commit()

    # 更新 Redis 缓存（全量回写，简化一致性）
    try:
        r = get_redis_client()
        cache_key = f"{_CACHE_PREFIX}:{tenant_id}:{category_id or '_none'}"
        await r.set(
            cache_key,
            json.dumps(template_value, ensure_ascii=False),
            ex=TENANT_ATTR_CACHE_TTL,
        )
        # 清除全部分类缓存，避免其他分类读到旧数据
        await r.delete(f"{_CACHE_PREFIX}:{tenant_id}:__all__")
    except Exception:
        logger.debug("Redis 更新租户属性缓存失败: tenant_id=%s", tenant_id)

    return validated
