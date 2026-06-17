"""动态 SQL Builder：根据租户属性配置构建 attrs_json 查询条件。

支持 attr_query_strategy：
- jsonb_bool:   attrs_json -> 'attr' ->> 'key' = 'true'
- jsonb_number: (attrs_json -> 'attr' ->> 'key')::numeric {op} {value}
- jsonb_text:   attrs_json -> 'attr' ->> 'key' ILIKE '%value%'
- jsonb_equals: attrs_json -> 'attr' ->> 'key' = 'value'
- jsonb_contains: attrs_json -> 'attr' -> 'key' ? 'value' （数组包含）
"""

from __future__ import annotations

from typing import Any

from app.schemas.tenant import AttributeDef


def build_attr_condition(
    ad: AttributeDef,
    value: Any,
) -> str | None:
    """根据属性定义和过滤值构建单条 SQL WHERE 条件片段。

    Args:
        ad: 属性定义
        value: 过滤值

    Returns:
        SQL 条件字符串，或 None（无法构建时）
    """
    if value is None:
        return None

    path_parts = ad.query_path or ["attr", ad.key]
    json_path = " -> ".join(f"'{p}'" for p in path_parts)

    if ad.query_strategy == "jsonb_bool":
        bool_val = _to_bool(value)
        if bool_val is None:
            return None
        val_str = "true" if bool_val else "false"
        return f"attrs_json -> {json_path} = '{val_str}'::jsonb"

    if ad.query_strategy == "jsonb_number":
        num_val = _to_number(value)
        if num_val is None:
            return None
        return f"(attrs_json -> {json_path})::text::numeric = {num_val}"

    if ad.query_strategy == "jsonb_text":
        text_val = _to_text(value)
        if not text_val:
            return None
        escaped = text_val.replace("'", "''")
        return f"attrs_json -> {json_path} ->> 'text' ILIKE '%{escaped}%'"

    if ad.query_strategy == "jsonb_equals":
        text_val = _to_text(value)
        if not text_val:
            return None
        escaped = text_val.replace("'", "''")
        return f"attrs_json -> {json_path} ->> 'text' = '{escaped}'"

    if ad.query_strategy == "jsonb_contains":
        text_val = _to_text(value)
        if not text_val:
            return None
        escaped = text_val.replace("'", "''")
        return f"attrs_json -> {json_path} ? '{escaped}'"

    return None


def build_attrs_filter_sql(
    filters: dict[str, Any],
    attribute_defs: list[AttributeDef],
) -> str | None:
    """根据多个属性过滤条件构建完整 SQL WHERE 子句。

    Args:
        filters: {key: value}，如 {"is_waterproof": True, "is_long_battery": 7}
        attribute_defs: 租户属性定义列表

    Returns:
        完整的 SQL WHERE 条件字符串，多条用 AND 连接。无有效条件时返回 None。
    """
    key_to_def = {ad.key: ad for ad in attribute_defs}
    conditions: list[str] = []

    for key, value in filters.items():
        ad = key_to_def.get(key)
        if ad is None:
            continue
        cond = build_attr_condition(ad, value)
        if cond:
            conditions.append(cond)

    if not conditions:
        return None

    return " AND ".join(conditions)


# ── 辅助函数 ──


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "yes", "1", "是"):
            return True
        if v in ("false", "no", "0", "否", "不是"):
            return False
    return None


def _to_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_text(value: Any) -> str | None:
    if not value:
        return None
    return str(value).strip()
