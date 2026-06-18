"""实体抽取 — 按场景分层：正则固定模式 + 别名匹配 + LLM 兜底。

策略：
  - 正则：价格、数量、订单号（模式固定，跨租户不变，永远用正则）
  - 别名匹配：分类名、商品属性（租户配置了 aliases，毫秒级命中）
  - LLM 兜底：别名匹配不到的剩余属性（极少情况，交给 Handler 处理）
"""

from __future__ import annotations

import re
from typing import Any

from app.schemas.tenant import AttributeDef

# ══ 正则模式（模式固定，跨租户不变） ══

# 价格区间: "500-1000 元", "500 到 1000"
_PRICE_RANGE = re.compile(
    r"(?P<min>\d{1,6})\s*(?:[-~至到]|\s{1,3})\s*(?P<max>\d{1,6})\s*(?P<unit>元|块|錢)?"
)
# 单价格: "不超过 200", "500 元", "3000 以内"
_PRICE_SINGLE = re.compile(
    r"(?:不超过?|低于?|小于|最多|预算|价格|价位)?\s*(?P<amount>\d{1,6})\s*(?:元|块|錢)?"
)
# 数量: "3 个", "5 件"
_QUANTITY = re.compile(r"(?P<qty>\d{1,3})\s*(?:个|件|台|只|条|双|瓶|箱)")
# 订单号: "订单 322296929084051456"（18位长整型）
_ORDER_ID = re.compile(r"订单[号#]?\s*(\d{15,20})")
# 否定检测：别名匹配时，匹配词前 3 个字含否定词 → boolean=false
_NEGATION = re.compile(r"(不|没|非|无|别|不要)")


# ══ 固定正则提取 ══


def extract_price_entities(text: str) -> dict[str, Any]:
    """抽取价格相关实体。"""
    entities: dict[str, Any] = {}

    range_match = _PRICE_RANGE.search(text)
    if range_match:
        if range_match.group("unit"):
            entities["price_min"] = int(range_match.group("min"))
            entities["price_max"] = int(range_match.group("max"))
            return entities

        before = text[: range_match.start()]
        after = text[range_match.end():]
        if any(
            kw in before + after
            for kw in (
                "元", "块", "錢", "价格", "价位", "预算",
                "以内", "以下", "不超过", "低于", "小于", "最多", "封顶",
                "以上", "超过", "高于", "最少",
            )
        ):
            entities["price_min"] = int(range_match.group("min"))
            entities["price_max"] = int(range_match.group("max"))
            return entities
        return entities

    single_match = _PRICE_SINGLE.search(text)
    if single_match:
        amount = int(single_match.group("amount"))
        before_text = text[: single_match.start()]
        matched_text = single_match.group()
        after_text = text[single_match.end():]
        all_before = before_text + matched_text

        ceiling_prefix = any(kw in all_before for kw in ("不超过", "低于", "小于", "最多", "预算"))
        ceiling_suffix = any(kw in after_text for kw in ("以内", "以下", "封顶"))
        floor = any(kw in after_text for kw in ("以上", "超过", "高于", "最少", "起步"))
        has_price_context = (
            ceiling_prefix or ceiling_suffix or floor
            or any(kw in matched_text + after_text for kw in ("元", "块", "錢"))
            or any(kw in after_text for kw in ("左右", "上下"))
            or any(kw in all_before for kw in ("价格", "价位"))
        )
        if not has_price_context:
            return entities

        if ceiling_suffix or (ceiling_prefix and not floor):
            entities["price_max"] = amount
        elif floor:
            entities["price_min"] = amount
        else:
            entities["price_min"] = amount
            entities["price_max"] = amount
    return entities


def extract_quantity(text: str) -> int | None:
    """抽取数量。"""
    match = _QUANTITY.search(text)
    if match:
        return int(match.group("qty"))
    return None


def extract_order_reference(text: str) -> str | None:
    """抽取订单号。"""
    match = _ORDER_ID.search(text)
    if match:
        return match.group(1)
    return None


# ══ 别名匹配（租户配置驱动） ══


def extract_category_by_tree(
    text: str,
    leaf_categories: list[tuple[int, str]],
) -> int | None:
    """通过租户叶子分类名精确匹配文本中的分类。

    Args:
        text: 用户消息
        leaf_categories: [(category_id, category_name), ...]

    Returns:
        命中的 category_id，未命中返回 None。多个命中时返回最长的。
    """
    best: tuple[int, str] | None = None
    for cat_id, cat_name in leaf_categories:
        if cat_name in text:
            if best is None or len(cat_name) > len(best[1]):
                best = (cat_id, cat_name)
    return best[0] if best else None


def extract_attrs_by_aliases(
    text: str,
    attribute_defs: list[AttributeDef],
) -> dict[str, Any]:
    """通过租户属性 aliases 匹配文本中的属性实体。

    支持类型：
      - boolean: 检查否定表达式 → true/false
      - number:  匹配词附近提取数值

    Args:
        text: 用户消息
        attribute_defs: 租户属性定义列表（含 aliases）

    Returns:
        {key: value}，只包含命中的属性
    """
    entities: dict[str, Any] = {}

    for ad in attribute_defs:
        for alias in ad.aliases:
            pos = text.find(alias)
            if pos == -1:
                continue

            if ad.type == "boolean":
                # 检查否定：匹配词前 3 个字是否含否定词
                before = text[max(0, pos - 3):pos]
                is_negated = bool(_NEGATION.search(before))
                entities[ad.key] = not is_negated
                break  # 命中即停，检查下一个属性

            if ad.type == "number":
                # 在别名附近提取数值
                num = _find_number_near(text, alias, pos)
                if num is not None:
                    entities[ad.key] = num
                break

            if ad.type in ("text", "enum"):
                # text/enum 只做存在性标记
                entities[ad.key] = alias
                break

    return entities


def _find_number_near(text: str, alias: str, alias_pos: int, window: int = 10) -> float | None:
    """在别名前后 window 字符内提取数值。"""
    start = max(0, alias_pos - window)
    end = min(len(text), alias_pos + len(alias) + window)
    nearby = text[start:end]
    # 匹配整数或小数
    m = re.search(r"(\d+(?:\.\d+)?)", nearby)
    if m:
        return float(m.group(1))
    return None


# ══ 分层提取入口 ══


def extract_baseline(text: str) -> dict[str, Any]:
    """基线实体提取（所有场景都跑，纯正则，毫秒级）。

    提取：价格、数量、订单号。
    """
    entities: dict[str, Any] = {}
    entities.update(extract_price_entities(text))

    qty = extract_quantity(text)
    if qty is not None:
        entities["quantity"] = qty

    order_ref = extract_order_reference(text)
    if order_ref is not None:
        entities["order_ref"] = order_ref

    return entities


def extract_product_entities(
    text: str,
    leaf_categories: list[tuple[int, str]] | None = None,
    attribute_defs: list[AttributeDef] | None = None,
) -> dict[str, Any]:
    """产品场景实体提取（只在 product.* 场景调用）。

    提取：分类 → category_id（别名匹配）、属性（别名匹配）。
    """
    entities: dict[str, Any] = {}

    if leaf_categories:
        cid = extract_category_by_tree(text, leaf_categories)
        if cid is not None:
            entities["category_id"] = cid

    if attribute_defs:
        attrs = extract_attrs_by_aliases(text, attribute_defs)
        if attrs:
            entities["raw_attrs"] = attrs

    return entities
