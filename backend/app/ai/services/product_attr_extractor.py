"""商品属性抽取器 — 根据产品字段（name/description/specs）通过 LLM 抽取结构化属性。

复用 prompt 构建 + validator + _build_attrs_json，与知识文档抽取共享同一套逻辑。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import gateway as llm_gateway
from app.ai.prompts.product_attribute_extraction import build_product_attr_extract_messages
from app.ai.services.attr_validator import validate_and_clean_attrs
from app.schemas.tenant import AttributeDef
from app.common.constants.config import PRODUCT_ATTR_EXTRACT_MAX_TOKENS
from app.integrations.llm_client import LLMUseCase
from app.models.product import Product
from app.services.tenant_template import get_tenant_attributes

logger = logging.getLogger(__name__)


async def extract_product_attributes(
    db: AsyncSession,
    tenant_id: int,
    product_id: int,
) -> None:
    """根据商品字段（名称/描述/规格）通过 LLM 抽取结构化属性，直接写入 Product 表。

    在独立 DB 会话中运行，用于后台任务。
    """
    product = await db.get(Product, product_id)
    if product is None or product.tenant_id != tenant_id:
        return

    attribute_defs = await get_tenant_attributes(
        db, tenant_id,
        category_id=str(product.category_id) if product.category_id else "",
    )
    if not attribute_defs:
        logger.info("租户未配置属性模板，跳过抽取: tenant_id=%s product_id=%s category_id=%s", tenant_id, product_id, product.category_id)
        return

    # 从 product 对象读取字段拼接输入文本
    content = _build_input_text(
        product.name or "",
        product.description,
        product.specs,
    )
    if not content.strip():
        logger.info("商品字段为空，跳过属性抽取: product_id=%s", product_id)
        return

    # 1. LLM 抽取
    messages = build_product_attr_extract_messages(content, product.name, attribute_defs)
    raw = await llm_gateway.complete(
        LLMUseCase.PRODUCT_ATTR_EXTRACT,
        messages,
        tenant_id=tenant_id,
        max_tokens=PRODUCT_ATTR_EXTRACT_MAX_TOKENS,
        temperature=0.2,
    )

    data = _extract_final_json(raw)
    if data is None:
        logger.warning("LLM 属性抽取返回非 JSON: %s", raw[:200])
        return

    # 2. 校验清洗
    data = validate_and_clean_attrs(data, attribute_defs)

    # 2.5 规则兜底：对 LLM 未抽取到的 boolean/enum 属性做关键词匹配
    data = _rule_based_fallback(data, content, product.name or "", attribute_defs)

    # 3. 写入 Product 表
    product.attrs_json = _build_attrs_json(data)
    product.feature_tags = _clean_tags(data.get("feature_tags"))

    logger.info(
        "商品属性抽取完成: product_id=%s attrs=%s features=%s",
        product_id,
        list((product.attrs_json or {}).get("attr", {}).keys()),
        product.feature_tags,
    )


# ── 内部工具 ──


def _build_input_text(name: str = "", description: str | None = None, specs: dict | None = None) -> str:
    """拼接商品字段为 LLM 输入文本。"""
    parts: list[str] = []
    if name:
        parts.append(f"商品名称：{name}")
    if description:
        parts.append(f"商品描述：{description}")
    if specs:
        parts.append(f"规格参数：{json.dumps(specs, ensure_ascii=False)}")
    return "\n\n".join(parts)


def _extract_final_json(raw: str) -> dict | None:
    """从模型输出中提取 JSON，支持对象和数组两种格式。

    LLM 有时会返回对象（期望格式），有时会返回数组（容错）。
    数组格式：[{"key": "...", "value": ..., "evidence": "...", "confidence": 0.9}, ...]
    自动转换为对象格式：{"attr": {...}, "evidence": {...}, "confidence": {...}}
    """
    import re

    # 1. 尝试全量 parse（支持对象和数组）
    try:
        data = json.loads(raw.strip())
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            return _convert_array_to_object(data)
    except json.JSONDecodeError:
        pass

    # 2. 从 raw 中提取 JSON 子串
    # 优先找最外层的 [...]（数组）
    bracket_match = re.search(r"\[[\s\S]*\]", raw)
    if bracket_match:
        try:
            data = json.loads(bracket_match.group())
            if isinstance(data, list):
                return _convert_array_to_object(data)
        except json.JSONDecodeError:
            pass

    # 3. 找最外层的 {...}（对象）
    brace_match = re.search(r"\{[\s\S]*\}", raw)
    if brace_match:
        try:
            data = json.loads(brace_match.group())
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    return None


def _convert_array_to_object(arr: list[dict]) -> dict:
    """将数组格式 [{key, value, evidence, confidence}] 转换为对象格式。"""
    attr: dict[str, Any] = {}
    evidence: dict[str, str] = {}
    confidence: dict[str, float] = {}
    all_feature_tags: list[str] = []

    for item in arr:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if not key or not isinstance(key, str):
            continue
        attr[key] = item.get("value")

        ev = item.get("evidence")
        if isinstance(ev, str) and ev.strip():
            evidence[key] = ev.strip()

        cf = item.get("confidence")
        if cf is not None:
            try:
                confidence[key] = round(float(cf), 2)
            except (TypeError, ValueError):
                pass

        ft = item.get("feature_tags")
        if isinstance(ft, list):
            for t in ft:
                if isinstance(t, str) and t.strip() and t.strip() not in all_feature_tags:
                    all_feature_tags.append(t.strip())

    return {
        "attr": attr,
        "evidence": evidence,
        "confidence": confidence,
        "feature_tags": all_feature_tags,
    }


def _build_attrs_json(data: dict[str, Any]) -> dict[str, Any]:
    """从校验后的 data 构建最终 attrs_json：去 null，只保留有值的 key。"""
    raw_attr = data.get("attr") or {}
    raw_evidence = data.get("evidence") or {}
    raw_confidence = data.get("confidence") or {}

    attr: dict[str, Any] = {}
    evidence: dict[str, str] = {}
    confidence: dict[str, float] = {}

    for key, value in raw_attr.items():
        if value is None:
            continue
        attr[key] = value
        ev = raw_evidence.get(key)
        if isinstance(ev, str) and ev.strip():
            evidence[key] = ev.strip()
        confidence[key] = _safe_float(raw_confidence.get(key))

    return {
        "schema_version": 1,
        "attr": attr,
        "evidence": evidence,
        "confidence": confidence,
    }


# ── 否定词定义（用于规则兜底判断）──
_NEGATIONS = {"不", "没有", "无", "非", "未", "没", "无需", "不支持", "不带", "不具备"}


def _rule_based_fallback(
    data: dict[str, Any],
    content: str,
    product_name: str,
    attribute_defs: list[AttributeDef],
) -> dict[str, Any]:
    """关键词规则兜底：对 LLM 未抽取到的 boolean/enum 属性做规则匹配。

    利用属性定义中的 label/aliases 生成关键词，在商品文本中匹配，
    只填充 LLM 未命中（null 或缺失）且能明确匹配的键。
    text/number 类型规则无法可靠匹配，跳过。
    """
    combined = f"{product_name} {content}".lower()

    for attr_def in attribute_defs:
        key = attr_def.key

        # 只处理 LLM 未命中的键
        current = data.get("attr", {}).get(key)
        if current is not None:
            continue

        # boolean / enum 才适合规则匹配
        if attr_def.type not in ("boolean", "enum"):
            continue

        # 收集关键词
        keywords: set[str] = set()
        if attr_def.label:
            keywords.add(attr_def.label.lower())
        for alias in (attr_def.aliases or []):
            if alias.strip():
                keywords.add(alias.strip().lower())
        if not keywords:
            continue

        if attr_def.type == "boolean":
            matched = _match_bool_keyword(combined, keywords)
            if matched:
                _ensure_attr(data, key, True, f"规则匹配：商品信息包含关键词", 0.7)

        elif attr_def.type == "enum":
            for allowed in (attr_def.allowed_values or []):
                if allowed.strip().lower() in combined:
                    _ensure_attr(data, key, allowed, f"规则匹配到「{allowed}」", 0.65)
                    break

    return data


def _match_bool_keyword(text: str, keywords: set[str]) -> str | None:
    """在文本中查找 bool 关键词，且前方无否定词。返回匹配到的关键词。"""
    for kw in keywords:
        idx = text.find(kw)
        if idx == -1:
            continue
        # 检查关键词前的否定词
        start = max(0, idx - 6)
        before = text[start:idx]
        if any(neg in before for neg in _NEGATIONS):
            continue
        return kw
    return None


def _ensure_attr(data: dict, key: str, value: Any, evidence: str, confidence: float) -> None:
    """在 data 中设置属性值（保证嵌套 dict 存在）。"""
    data.setdefault("attr", {})[key] = value
    data.setdefault("evidence", {})[key] = evidence
    data.setdefault("confidence", {})[key] = confidence


def _clean_tags(raw_tags: object, *, max_count: int = 20, max_length: int = 12) -> list[str]:
    """清洗 LLM 返回的标签列表。"""
    if not isinstance(raw_tags, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_tags:
        tag = str(raw).strip()
        if not tag or len(tag) > max_length or tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
        if len(result) >= max_count:
            break
    return result


def _safe_float(value: Any) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0
