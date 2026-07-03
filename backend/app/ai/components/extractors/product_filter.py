"""ProductFilterExtractor — 商品筛选搜索场景的参数抽取器。

解决 core bug：用户说"有没有500以内的耳机推荐啊"时，
pipeline 只提取了价格（500），但没把"耳机"解析为 category_id。

分工策略：
  - LLM：分类匹配 + 属性筛选
  - 正则：价格抽取（固定模式，100% 可靠）
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.ai.components.extractors.base import ExtractionResult, ScenarioExtractor
from app.ai.context.session_context import SessionContext
from app.ai.llm.gateway import LLMUseCase, complete
from app.ai.prompts.product_extract import PRODUCT_FILTER_EXTRACT_PROMPT
from app.services.category_service import get_tenant_leaf_categories_cached_only
from app.services.tenant_template import get_all_tenant_attributes_cached_only

logger = logging.getLogger(__name__)

# Product 模型有独立 SQL 列的字段，不应放入 attrs_json 属性过滤
_PRODUCT_TOP_LEVEL_FIELDS: frozenset[str] = frozenset({
    "price", "category_id", "name", "sku", "stock", "floor_price", "is_sample",
})

# 价格正则
_RE_RANGE = re.compile(r"(\d{1,6})\s*(?:[-~至到])\s*(\d{1,6})\s*(?:元|块)?")
_RE_CEILING = re.compile(r"(?:不超过?|低于?|小于|最多|预算)\s*(\d{1,6})|(\d{1,6})\s*(?:以内|以下)")
_RE_FLOOR = re.compile(r"(?:超过|高于|不少于|至少|最少)\s*(\d{1,6})|(\d{1,6})\s*(?:以上|起步)")
_RE_BARE_PRICE = re.compile(r"(?:价格|预算|价位)?\s*(\d{1,6})\s*(?:元|块)")


def _fuzzy_match_category_name(
    cat_name: str,
    leaves: list[tuple[int, str]],
) -> str | None:
    """当 LLM 输出的分类名未精确命中叶子时，尝试模糊匹配。

    LLM 有时会把分类名缩写（如"笔记本电脑"→"电脑"），此函数做 substring 兜底。
    只匹配叶子分类名，不匹配父分类。
    """
    stripped = cat_name.strip().lower()
    if not stripped:
        return None

    candidates: list[str] = []
    for _, name in leaves:
        cn = name.strip().lower()
        if stripped in cn or cn in stripped:
            candidates.append(name)

    if not candidates:
        return None
    if len(candidates) == 1:
        logger.info("模糊匹配叶子分类: %s → %s", cat_name, candidates[0])
        return candidates[0]

    # 多个匹配 → 优先选最短的（通常最相关）
    candidates.sort(key=len)
    logger.info("模糊匹配叶子分类（多候选取最短）: %s → %s", cat_name, candidates[0])
    return candidates[0]


class ProductFilterExtractor(ScenarioExtractor):
    """商品筛选参数抽取器。

    从用户原文中提取分类、价格、属性等筛选条件。
    """

    async def extract(
        self,
        text: str,
        context: SessionContext,
        tenant_id: int,
        **kwargs: Any,
    ) -> ExtractionResult:
        stripped = text.strip()
        if not stripped:
            return ExtractionResult(need_clarification=True, reason="消息为空")

        # ── 1: 价格（正则，不依赖 LLM）──
        entities: dict[str, Any] = {}
        price = self._extract_price(stripped)
        if price is not None:
            pmin, pmax = price
            if pmin is not None:
                entities["price_min"] = pmin
            if pmax is not None:
                entities["price_max"] = pmax

        # ── 2: 获取租户叶子分类 + 属性定义，嵌入 prompt ──
        leaves = await get_tenant_leaf_categories_cached_only(tenant_id)
        attr_defs = await get_all_tenant_attributes_cached_only(tenant_id)

        # ── 3: LLM 抽取（分类 + 属性 + query）──
        llm_entities = await self._llm_extract(stripped, leaves, attr_defs)

        if llm_entities.get("query"):
            entities["query_text"] = llm_entities["query"]

        # ── 3.5: 回复模式（template / analysis）──
        reply_mode = llm_entities.get("reply_mode", "template")
        if reply_mode in ("template", "analysis"):
            entities["reply_mode"] = reply_mode

        # ── 4: 分类（LLM 输出叶子分类名，代码查表转 ID，支持多分类 category_names）──
        cat_name = (llm_entities.get("category_name") or "").strip()
        cat_names = llm_entities.get("category_names") or []
        if not cat_name and cat_names:
            cat_name = cat_names[0]  # 以 category_names 为准时取第一个

        if leaves:
            leaf_map = {name.strip(): cid for cid, name in leaves}

            # 先处理多分类 category_names
            matched_ids: list[int] = []
            if cat_names:
                for name in cat_names:
                    name = name.strip()
                    cid = leaf_map.get(name)
                    if cid is not None:
                        matched_ids.append(cid)

            # 单分类 category_name（含从 category_names[0] 取的）
            if not matched_ids and cat_name:
                cid = leaf_map.get(cat_name)
                if cid is not None:
                    matched_ids = [cid]
                else:
                    # 精确匹配失败 → 尝试模糊匹配（缩写兜底）
                    fuzzy_name = _fuzzy_match_category_name(cat_name, leaves)
                    if fuzzy_name and fuzzy_name != cat_name:
                        cid = leaf_map.get(fuzzy_name)
                        if cid is not None:
                            matched_ids = [cid]

            if matched_ids:
                if len(matched_ids) == 1:
                    entities["category_id"] = matched_ids[0]
                else:
                    entities["category_ids"] = matched_ids
                entities["category_name"] = cat_name

        # ── 5: 属性筛选 — 排除 Product 顶层列（有独立 SQL 列，不应走 attrs_json）──
        attr_filters = llm_entities.get("attr_filters") or {}
        if attr_filters:
            conflicting = _PRODUCT_TOP_LEVEL_FIELDS & set(attr_filters.keys())
            if conflicting:
                logger.debug("从 attr_filters 排除顶层列: %s", conflicting)
                attr_filters = {k: v for k, v in attr_filters.items() if k not in _PRODUCT_TOP_LEVEL_FIELDS}
            if attr_filters:
                entities["attr_filters"] = attr_filters

        return ExtractionResult(
            entities=entities,
            reason=self._build_reason(entities),
        )

    # ── 内部方法 ──

    @staticmethod
    def _extract_price(text: str) -> tuple[int | None, int | None] | None:
        """正则提取价格，返回 (min_price, max_price)，未命中返回 None。"""
        # 范围："500-1000", "300到500"
        m = _RE_RANGE.search(text)
        if m:
            return int(m.group(1)), int(m.group(2))

        # 上限："500以内", "不超过300"
        m = _RE_CEILING.search(text)
        if m:
            val = m.group(1) or m.group(2)
            return None, int(val)

        # 下限："500以上", "超过300"
        m = _RE_FLOOR.search(text)
        if m:
            val = m.group(1) or m.group(2)
            return int(val), None

        # 裸价格："500元", "预算300"
        m = _RE_BARE_PRICE.search(text)
        if m:
            val = int(m.group(1))
            return val, val

        return None

    @staticmethod
    async def _llm_extract(
        text: str,
        leaves: list[tuple[int, str]] | None,
        attr_defs: list[Any] | None,
    ) -> dict[str, Any]:
        """调用 LLM 抽取筛选参数，叶子分类 + 属性定义嵌入 prompt。"""
        if leaves:
            cat_lines = "\n".join(f"  {cid} → {cname}" for cid, cname in leaves)
            category_section = f"=== 叶子分类列表 ===\n{cat_lines}\n==================="
        else:
            category_section = "（无分类数据）"

        if attr_defs:
            simple_attrs = []
            for ad in attr_defs:
                item = {"key": ad.key, "label": ad.label, "type": ad.type}
                if ad.type == "enum" and ad.allowed_values:
                    item["allowed_values"] = ad.allowed_values
                simple_attrs.append(item)
            attr_lines = json.dumps(simple_attrs, ensure_ascii=False, indent=2)
            attribute_section = f"=== 属性定义 ===\n{attr_lines}\n================"
        else:
            attribute_section = "（无属性定义）"

        messages = [
            {"role": "system", "content": PRODUCT_FILTER_EXTRACT_PROMPT.format(
                category_list=category_section,
                attribute_list=attribute_section,
            )},
            {"role": "user", "content": f"用户消息：{text}"},
        ]
        for attempt in (1, 2):
            try:
                raw = await complete(
                    LLMUseCase.PRODUCT_EXTRACT,
                    messages,
                    max_tokens=500,
                    temperature=0.1,
                )
                content = (raw or "").strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[-1]
                    if content.endswith("```"):
                        content = content[:-3]
                    content = content.strip()
                return json.loads(content)
            except json.JSONDecodeError:
                logger.debug("LLM 筛选抽取格式异常: %s", (raw or "")[:80])
                return {}
            except Exception as exc:
                if attempt == 1:
                    logger.debug("LLM 筛选抽取异常，重试一次: %s", exc)
                    continue
                logger.warning("LLM 筛选抽取最终失败: %s", exc)
                return {}

    @staticmethod
    def _build_reason(entities: dict[str, Any]) -> str:
        parts: list[str] = []
        if "category_id" in entities:
            parts.append(f"category_id={entities['category_id']}")
            if "category_name" in entities:
                parts.append(f"({entities['category_name']})")
        if "category_ids" in entities:
            parts.append(f"category_ids={entities['category_ids']}")
            if "category_name" in entities:
                parts.append(f"({entities['category_name']})")
        if "price_min" in entities:
            parts.append(f"price>={entities['price_min']}")
        if "price_max" in entities:
            parts.append(f"price<={entities['price_max']}")
        if "attr_filters" in entities:
            parts.append(f"attrs={entities['attr_filters']}")
        return "筛选参数: " + ", ".join(parts) if parts else "无筛选参数"
