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

    attribute_defs = await get_tenant_attributes(db, tenant_id)
    if not attribute_defs:
        logger.info("租户未配置属性模板，跳过抽取: tenant_id=%s product_id=%s", tenant_id, product_id)
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

    # 3. 写入 Product 表
    product.attrs_json = _build_attrs_json(data)
    product.feature_tags = _clean_tags(data.get("feature_tags"))
    product.scenario_tags = _clean_tags(data.get("scenario_tags"))

    logger.info(
        "商品属性抽取完成: product_id=%s attrs=%s features=%s warnings=%s",
        product_id,
        list((product.attrs_json or {}).get("attr", {}).keys()),
        product.feature_tags,
        data.get("warnings", []),
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
    """从模型输出中提取最后一个有效 JSON 对象。"""
    import re

    last_brace = raw.rfind("{")
    if last_brace < 0:
        return None
    try:
        data = json.loads(raw[last_brace:])
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        logger.debug("首次 JSON 解析失败，尝试正则提取: raw=%s", raw[:100])
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            logger.debug("正则提取 JSON 解析失败: raw=%s", raw[:100])
    return None


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
