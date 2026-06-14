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
    """规范化租户商品属性模板字段列表。

    参数：
        value: 原始模板值（可以是 JSON 数组或 None）。
        strict: 严格模式，非合法数组会直接抛异常，而非静默返回空列表。

    返回：
        去重、去空格后的合法字段名列表。

    异常：
        ValueError（strict 模式）: 非字符串数组、含空字段名。
    """
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
    """规范化商品属性 JSON，强制输出 {"attr": {...}} 结构。

    SaaS 多租户下，每个租户可能配置不同的 template_fields，只保留模板允许的字段。
    非标量值（list、dict 等）会被 JSON 序列化为字符串存储。

    参数：
        value: 原始属性 JSON（支持 {"attr": {}} 或 {} 两种输入）。
        template_fields: 租户模板允许的字段列表，None 表示不做字段过滤。

    返回：
        规范化后的 {"attr": {key: value, ...}} 字典。
    """
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
    """查询租户配置的商品属性模板字段列表。

    从 Tenant.template_json 读取并规范化为字段名列表。

    参数：
        db: 异步数据库会话。
        tenant_id: 租户 ID。

    返回：
        去重后的合法字段名列表。
    """
    value = await db.scalar(select(Tenant.template_json).where(Tenant.id == tenant_id))
    return normalize_template_json(value)


async def update_tenant_template(db: AsyncSession, tenant_id: int, template_json: object) -> list[str]:
    """更新租户的商品属性模板。

    使用 strict 模式校验输入，确保模板字段合法后再持久化。

    参数：
        db: 异步数据库会话。
        tenant_id: 租户 ID。
        template_json: 新的模板字段（字符串数组）。

    返回：
        规范化后的模板字段列表。

    异常：
        ValueError: 租户不存在或已删除；模板格式不合法。
    """
    template = normalize_template_json(template_json, strict=True)
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None or tenant.deleted_at is not None:
        raise ValueError("租户不存在")
    tenant.template_json = template
    await db.commit()
    await db.refresh(tenant)
    return template
