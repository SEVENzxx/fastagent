"""租户商品属性模板工具。

提供商品属性模板的规范化、校验和持久化能力。租户可在后台管理配置自定义模板字段，
创建商品时 attrs_json 会按模板自动筛选保留合法字段。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant


ATTRS_JSON_EMPTY: dict[str, dict[str, Any]] = {"attr": {}}


def normalize_template_json(value: object, *, strict: bool = False) -> list[str]:
    """规范化租户商品属性模板字段列表。"""
    if value is None:
        return []
    if not isinstance(value, list):
        if strict:
            raise ValueError('template_json 必须是字符串数组，例如 ["field1","field2"]')
        return []

    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            if strict:
                raise ValueError("template_json 只能包含字符串字段名")
            continue
        field = item.strip()
        if not field:
            if strict:
                raise ValueError("template_json 不能包含空字段名")
            continue
        if field in seen:
            continue
        seen.add(field)
        result.append(field)
    return result


def normalize_attrs_json(value: object, template_fields: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """规范化商品属性 JSON，强制输出 {"attr": {...}} 结构。"""
    has_template = template_fields is not None
    allowed = set(template_fields or [])
    raw_attr: object
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
            if not field or (has_template and field not in allowed):
                continue
            if raw_value is None or isinstance(raw_value, (str, int, float, bool)):
                attr[field] = raw_value
            else:
                attr[field] = json.dumps(raw_value, ensure_ascii=False, sort_keys=True)
    return {"attr": attr}


async def get_tenant_template(db: AsyncSession, tenant_id: int) -> list[str]:
    """查询租户配置的商品属性模板字段列表。"""
    value = await db.scalar(select(Tenant.template_json).where(Tenant.id == tenant_id))
    return normalize_template_json(value)


async def update_tenant_template(db: AsyncSession, tenant_id: int, template_json: object) -> list[str]:
    """更新租户的商品属性模板。"""
    template = normalize_template_json(template_json, strict=True)
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None or tenant.deleted_at is not None:
        raise ValueError("租户不存在")
    tenant.template_json = template
    await db.commit()
    await db.refresh(tenant)
    return template
