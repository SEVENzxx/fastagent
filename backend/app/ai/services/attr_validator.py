"""LLM 属性抽取结果后处理校验器。

无论 prompt 多严格，LLM 输出都需要校验：
1. 删除 schema 之外的 key
2. schema 内缺失的 key 补 null
3. boolean 类型必须是 true/false/null
4. number 类型必须是数字/null
5. enum 类型必须在 allowed_values 里
6. evidence 为空时 confidence 不能高
7. attr 为 null 时 confidence 应该为 0 或很低
"""

from __future__ import annotations

import logging
from typing import Any

from app.schemas.tenant import AttributeDef

logger = logging.getLogger(__name__)

# evidence 为空时，confidence 上限
MAX_CONFIDENCE_WITHOUT_EVIDENCE = 0.5
# attr 为 null 时，confidence 上限
MAX_CONFIDENCE_WHEN_NULL = 0.1


def validate_and_clean_attrs(
    data: dict[str, Any],
    attribute_defs: list[AttributeDef],
) -> dict[str, Any]:
    """校验并清理 LLM 返回的属性抽取结果。

    兼容两种 LLM 输出格式：
    - 嵌套: {"attr": {"key": value, ...}, "evidence": {...}, ...}
    - 扁平: {"key": value, "evidence": "...", ...}  （自动归一化为嵌套）

    Args:
        data: LLM 返回的 JSON 解析结果（非 None）
        attribute_defs: 租户配置的属性定义列表

    Returns:
        清洗后的 data dict（原地修改并返回）
    """
    key_to_def: dict[str, AttributeDef] = {ad.key: ad for ad in attribute_defs}
    schema_keys = set(key_to_def.keys())

    # ── 归一化：自动识别扁平/嵌套格式 ──
    raw_attrs = data.get("attr") or data.get("attrs_json")
    if isinstance(raw_attrs, dict):
        pass  # 嵌套格式，直接用
    else:
        # 扁平格式：把 data 顶层中属于 schema_keys 的字段提取出来
        raw_attrs = {k: data[k] for k in schema_keys & set(data.keys())}

    raw_evidence = data.get("evidence") or {}
    raw_confidence = data.get("confidence") or {}

    # ── 扁平格式：evidence/confidence 可能是标量，按非 null attr key 分发 ──
    non_null_keys_for_ev = [k for k, v in raw_attrs.items() if v is not None]
    if not isinstance(raw_evidence, dict):
        raw_evidence = {k: raw_evidence for k in non_null_keys_for_ev} if isinstance(raw_evidence, str) and non_null_keys_for_ev else {}
    if not isinstance(raw_confidence, dict):
        raw_confidence = {k: raw_confidence for k in non_null_keys_for_ev} if isinstance(raw_confidence, (int, float)) and non_null_keys_for_ev else {}
    warnings: list[str] = list(data.get("warnings") or [])
    if not isinstance(warnings, list):
        warnings = []

    cleaned_attrs: dict[str, Any] = {}

    for key, ad in key_to_def.items():
        raw_value = raw_attrs.get(key)
        evidence = raw_evidence.get(key)
        confidence = _safe_float(raw_confidence.get(key))

        # 1. 类型校验与转换
        cleaned_value = _validate_value_type(raw_value, ad, warnings)

        # 2. evidence 校验
        if isinstance(evidence, str) and evidence.strip():
            evidence = evidence.strip()
        else:
            evidence = None

        # 3. evidence 为空时降低 confidence
        if not evidence and confidence > MAX_CONFIDENCE_WITHOUT_EVIDENCE:
            warnings.append(f"'{key}' 证据为空但置信度偏高 ({confidence})，已下调")
            confidence = min(confidence, MAX_CONFIDENCE_WITHOUT_EVIDENCE)

        # 4. attr 为 null 时降低 confidence
        if cleaned_value is None and confidence > MAX_CONFIDENCE_WHEN_NULL:
            confidence = min(confidence, MAX_CONFIDENCE_WHEN_NULL)

        cleaned_attrs[key] = cleaned_value
        raw_evidence[key] = evidence
        raw_confidence[key] = round(confidence, 2)

    # 5. 删除 schema 之外的 key
    extra_keys = set(raw_attrs.keys()) - schema_keys
    for ek in extra_keys:
        cleaned_attrs.pop(ek, None)
        raw_evidence.pop(ek, None)
        raw_confidence.pop(ek, None)
        warnings.append(f"删除 schema 外字段: '{ek}'")

    # 6. 补全 schema 中缺失的 key
    for key in schema_keys - set(cleaned_attrs.keys()):
        cleaned_attrs[key] = None
        raw_evidence[key] = None
        raw_confidence[key] = 0.0
        warnings.append(f"schema 缺失 key 已补 null: '{key}'")

    data["attr"] = cleaned_attrs
    data["evidence"] = raw_evidence
    data["confidence"] = raw_confidence
    data["warnings"] = warnings

    if warnings:
        logger.info("属性抽取校验警告: %s", warnings)

    return data


def _validate_value_type(
    value: Any,
    ad: AttributeDef,
    warnings: list[str],
) -> Any:
    """按属性类型校验并转换值。"""
    if value is None:
        return None

    if ad.type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            v_lower = value.strip().lower()
            if v_lower in ("true", "yes", "1", "是"):
                return True
            if v_lower in ("false", "no", "0", "否", "不是"):
                return False
        warnings.append(f"'{ad.key}' 期望 boolean，收到 '{value}'，已改为 null")
        return None

    if ad.type == "number":
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except (TypeError, ValueError):
                pass
        warnings.append(f"'{ad.key}' 期望 number，收到 '{value}'，已改为 null")
        return None

    if ad.type == "enum":
        v_str = str(value).strip()
        if v_str in ad.allowed_values:
            return v_str
        warnings.append(f"'{ad.key}' 值 '{v_str}' 不在 allowed_values {ad.allowed_values} 中，已改为 null")
        return None

    if ad.type == "text":
        return str(value).strip() if value is not None else None

    return value


def _safe_float(value: Any) -> float:
    """安全转为 float。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
