"""租户商品属性模板工具。

提供商品属性模板的规范化、校验和持久化能力。
格式：{"attributes": [AttributeDef, ...]}
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


def normalize_template_to_attributes(value: object) -> list[AttributeDef]:
    """将 template_json 范化为 AttributeDef 列表。

    仅处理新格式 {"attributes": [...]}，旧格式不再支持。
    """
    if value is None:
        return []
    if not isinstance(value, dict):
        return []

    raw_attrs = value.get("attributes")
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


async def get_tenant_attributes(db: AsyncSession, tenant_id: int) -> list[AttributeDef]:
    """查询租户配置的商品属性定义列表（Redis 缓存，24h TTL）。"""
    cache_key = f"{_CACHE_PREFIX}:{tenant_id}"
    try:
        r = get_redis_client()
        cached = await r.get(cache_key)
        if cached:
            raw = json.loads(cached)
            attrs = normalize_template_to_attributes(raw)
            if attrs:
                return attrs
    except Exception:
        logger.debug("Redis 读取租户属性缓存失败，回退 DB: tenant_id=%s", tenant_id)

    value = await db.scalar(select(Tenant.template_json).where(Tenant.id == tenant_id))
    attrs = normalize_template_to_attributes(value)

    try:
        r = get_redis_client()
        await r.set(
            cache_key,
            json.dumps(value, ensure_ascii=False),
            ex=TENANT_ATTR_CACHE_TTL,
        )
    except Exception:
        logger.debug("Redis 写入租户属性缓存失败: tenant_id=%s", tenant_id)

    return attrs


async def update_tenant_template(
    db: AsyncSession,
    tenant_id: int,
    attributes: list[AttributeDef],
) -> list[AttributeDef]:
    """更新租户的商品属性模板，同时刷新 Redis 缓存。"""
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

    template_value = {
        "attributes": [ad.model_dump() for ad in validated],
    }
    tenant.template_json = template_value
    await db.commit()
    await db.refresh(tenant)

    # 更新 Redis 缓存
    try:
        r = get_redis_client()
        cache_key = f"{_CACHE_PREFIX}:{tenant_id}"
        await r.set(
            cache_key,
            json.dumps(template_value, ensure_ascii=False),
            ex=TENANT_ATTR_CACHE_TTL,
        )
    except Exception:
        logger.debug("Redis 更新租户属性缓存失败: tenant_id=%s", tenant_id)

    return validated
