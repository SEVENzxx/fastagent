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
from app.services.category_service import (
    get_tenant_category_hierarchy_cached_only,
    get_tenant_leaf_categories_cached_only,
)
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


def _resolve_parent_to_descendant_ids(
    cat_name: str,
    hierarchy: list[tuple[int, str, int | None]],
) -> list[int]:
    """将父分类名称解析为其所有子孙分类 ID（含自身，递归全部层级）。

    Args:
        cat_name: 父分类名称（如"电脑办公"）。
        hierarchy: 全部分类 [(id, name, parent_id), ...]。

    Returns:
        子孙 ID 列表（含自身），无匹配返回空列表。
    """
    # parent_id → [child_id]
    parent_children: dict[int | None, list[int]] = {}
    for cid, _, pid in hierarchy:
        parent_children.setdefault(pid, []).append(cid)

    # 找到匹配的父分类 ID
    parent_id = None
    for cid, cname, _ in hierarchy:
        if cname.strip() == cat_name:
            parent_id = cid
            break
    if parent_id is None:
        return []

    # DFS 收集所有子孙节点（含自身）
    result: list[int] = []
    stack = [parent_id]
    while stack:
        node = stack.pop()
        result.append(node)
        stack.extend(parent_children.get(node, []))
    return result


def _format_category_tree(
    hierarchy: list[tuple[int, str, int | None]],
) -> str:
    """将分类层级格式化为带缩进的树形文本，用于 LLM prompt。"""
    if not hierarchy:
        return "（无分类数据）"

    children: dict[int | None, list[int]] = {}
    id_name: dict[int, str] = {}
    for cid, cname, pid in hierarchy:
        children.setdefault(pid, []).append(cid)
        id_name[cid] = cname

    # 找出所有非叶子 ID（有子分类的）
    non_leaf_ids = {pid for pid in children if pid is not None}

    lines: list[str] = []
    stack = [(pid, 0) for pid in children.get(None, [])]  # 根节点
    # 按 sort_order 排序（如果 hierarchy 本身就是有序的则跳过）
    while stack:
        cid, depth = stack.pop()
        name = id_name.get(cid, "")
        is_parent = cid in non_leaf_ids
        prefix = "  " * depth + ("└ " if depth > 0 else "")
        suffix = "（父分类）" if is_parent else ""
        lines.append(f"{prefix}{name}{suffix}")
        # 子节点逆序入栈，保持显示顺序
        for child in reversed(children.get(cid, [])):
            stack.append((child, depth + 1))

    return "\n".join(lines)


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

        # ── 2: 获取租户分类层级 + 属性定义，嵌入 prompt ──
        leaves = await get_tenant_leaf_categories_cached_only(tenant_id)
        hierarchy = await get_tenant_category_hierarchy_cached_only(tenant_id)
        attr_defs = await get_all_tenant_attributes_cached_only(tenant_id)

        # ── 3: LLM 抽取（分类 + 属性 + query）──
        llm_entities = await self._llm_extract(stripped, hierarchy or leaves, attr_defs)

        if llm_entities.get("query"):
            entities["query_text"] = llm_entities["query"]

        # ── 3.5: 回复模式（template / analysis）──
        reply_mode = llm_entities.get("reply_mode", "template")
        if reply_mode in ("template", "analysis"):
            entities["reply_mode"] = reply_mode

        # ── 4: 分类（LLM 输出分类名，代码查表转 ID，支持父分类→子叶子解析）──
        cat_name = (llm_entities.get("category_name") or "").strip()
        if cat_name and leaves:
            leaf_map = {name.strip(): cid for cid, name in leaves}

            # 先查叶子分类
            cat_id = leaf_map.get(cat_name)
            if cat_id is not None:
                entities["category_id"] = cat_id
                entities["category_name"] = cat_name
            elif hierarchy:
                # 叶子没匹配到 → 查父分类，解析到其所有子孙 ID（含中间节点）
                descendant_ids = _resolve_parent_to_descendant_ids(cat_name, hierarchy)
                if descendant_ids:
                    if len(descendant_ids) == 1:
                        entities["category_id"] = descendant_ids[0]
                        entities["category_name"] = cat_name
                    else:
                        entities["category_ids"] = descendant_ids
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
        categories: list[tuple[int, str]] | list[tuple[int, str, int | None]] | None,
        attr_defs: list[Any] | None,
    ) -> dict[str, Any]:
        """调用 LLM 抽取筛选参数，分类层级 + 属性定义嵌入 prompt。

        categories 可以是叶子分类列表 [(id, name)] 或完整层级 [(id, name, parent_id)]。
        有完整层级时优先用树形展示，LLM 能识别父分类名称。
        """
        if categories:
            # 判断是否为完整层级（含 parent_id）
            if categories and len(categories[0]) == 3:
                cat_lines = _format_category_tree(categories)
            else:
                cat_lines = "\n".join(f"  {cid} → {cname}" for cid, cname in categories)
            category_section = f"=== 分类层级 ===\n{cat_lines}\n==================="
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
