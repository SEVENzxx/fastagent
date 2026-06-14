"""SemanticRecommendExtractor — 语义推荐参数抽取组件。

将用户自然语言推荐请求转化为结构化搜索过滤条件。
使用 LLM 进行语义理解，输出与 ProductSkill.search_products 兼容的参数字典。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.ai.llm import gateway as llm_gateway
from app.ai.prompts.semantic_recommend import build_semantic_recommend_messages
from app.config import settings
from app.integrations.llm_client import LLMUseCase

logger = logging.getLogger(__name__)


class SemanticRecommendExtractor:
    """语义推荐参数抽取器。

    用法：
        params = await SemanticRecommendExtractor.extract("推荐一款防水耳机", tenant_id=1)
        # → {"query_text": "防水耳机", "category_text": "耳机", ...}
    """

    @staticmethod
    async def extract(
        text: str,
        tenant_id: int,
    ) -> dict[str, Any]:
        """从自然语言中抽取搜索参数。

        返回 dict，包含 query_text / category_text / min_price / max_price / features。
        LLM 失败或返回格式异常时降级为纯文本搜索。
        """
        if not text.strip():
            return {"query_text": "", "category_text": "", "min_price": None, "max_price": None, "features": []}

        messages = build_semantic_recommend_messages(text)
        try:
            raw = await llm_gateway.complete(
                LLMUseCase.PRODUCT_SEMANTIC_SEARCH,
                messages,
                tenant_id=tenant_id,
                max_tokens=512,
                temperature=0.0,
            )
            data = _parse_json(raw)
            if not data:
                logger.warning("语义推荐 LLM 返回空或非 JSON: raw=%s", raw[:200])
                return _fallback(text)

            return {
                "query_text": str(data.get("query_text", text))[:100],
                "category_text": str(data.get("category_text", ""))[:50],
                "min_price": _safe_float(data.get("min_price")),
                "max_price": _safe_float(data.get("max_price")),
                "features": data.get("features", []),
            }
        except Exception as exc:
            logger.warning("语义推荐 LLM 抽取失败: tenant_id=%s error=%s", tenant_id, exc)
            return _fallback(text)


def _parse_json(raw: str) -> dict | None:
    """安全解析 JSON，支持从文本中提取 JSON 块。"""
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            try:
                data = json.loads(match.group())
                return data if isinstance(data, dict) else None
            except json.JSONDecodeError:
                pass
    return None


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fallback(text: str) -> dict[str, Any]:
    """LLM 不可用时的降级：将用户原文作为 query_text。"""
    return {"query_text": text[:200], "category_text": "", "min_price": None, "max_price": None, "features": []}
