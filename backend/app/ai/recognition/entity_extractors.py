"""粗实体抽取 — 只做类型提取和语义归一化，不查业务 ID。

RecognitionPipeline 的实体是粗提示，不是最终抽参结果。
业务 ID 映射由 Component 层完成（CategoryResolver, ProductReferenceResolver 等）。
"""

from __future__ import annotations

import re
from typing import Any


# ══ 正则模式 ══

# 价格区间: "500-1000 元", "500 到 1000", "五百到一千"
_PRICE_RANGE = re.compile(
    r"(?P<min>\d{1,6})\s*(?:[-~至到]|\s{1,3})\s*(?P<max>\d{1,6})\s*(?P<unit>元|块|錢)?"
)
# 单价格: "不超过 200", "500 元", "3000 以内", "200 左右"
# 注意：后缀限定词（以内/以下/封顶）不纳入 match，留在 suffix 供边界判断
_PRICE_SINGLE = re.compile(
    r"(?:不超过?|低于?|小于|最多|预算|价格|价位)?\s*(?P<amount>\d{1,6})\s*(?:元|块|錢)?"
)
# 数量: "3 个", "5 件"
_QUANTITY = re.compile(r"(?P<qty>\d{1,3})\s*(?:个|件|台|只|条|双|瓶|箱)")
# 订单号: "订单 123456"
_ORDER_ID = re.compile(r"订单[号#]?\s*(\d{6,20})")
# 商品分类指示: "有什么 X", "有 X 吗", "X 有什么"
_CATEGORY_HINT = re.compile(r"(?:有什么|有.*吗|找|想要|看看)\s*(?P<cat>\S{2,10})")
# 分类指示停用词 — 对比/问答/政策相关词不视为分类
_CATEGORY_STOP_WORDS: frozenset[str] = frozenset({
    "区别", "不同", "差别", "优惠", "政策",
    "订单", "物流", "发货", "售后", "保修", "退换", "退款", "发票",
})


def extract_price_entities(text: str) -> dict[str, Any]:
    """抽取价格相关实体。

    Returns:
        dict 包含 price_min, price_max 等，无值时不包含对应键。
        数字附近没有价格语义词时返回空 dict（避免误抽数量/订单号）。
    """
    entities: dict[str, Any] = {}

    # 价格区间优先
    range_match = _PRICE_RANGE.search(text)
    if range_match:
        # 有明确价格单位，或附近有价格语义词，才认为是价格区间
        if range_match.group("unit"):
            entities["price_min"] = int(range_match.group("min"))
            entities["price_max"] = int(range_match.group("max"))
            return entities

        before = text[: range_match.start()]
        after = text[range_match.end() :]
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

        # 没有价格语境，不抽取
        return entities

    # 单价格
    single_match = _PRICE_SINGLE.search(text)
    if single_match:
        amount = int(single_match.group("amount"))
        before_text = text[: single_match.start()]
        matched_text = single_match.group()
        after_text = text[single_match.end() :]

        # 至少有一个价格语义词附近出现才视为有效价格
        all_before = before_text + matched_text
        ceiling_prefix = any(
            kw in all_before
            for kw in ("不超过", "低于", "小于", "最多", "预算")
        )
        ceiling_suffix = any(
            kw in after_text
            for kw in ("以内", "以下", "封顶")
        )
        floor = any(
            kw in after_text
            for kw in ("以上", "超过", "高于", "最少", "起步")
        )
        has_price_context = (
            ceiling_prefix
            or ceiling_suffix
            or floor
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
    """抽取订单号引用。"""
    match = _ORDER_ID.search(text)
    if match:
        return match.group(1)
    return None


def extract_category_hint(text: str) -> str | None:
    """粗抽取分类文本提示（非业务 ID）。

    停用词（区别/优惠/政策等）不返回，避免对比/问答句污染分类。
    """
    match = _CATEGORY_HINT.search(text)
    if match:
        cat = match.group("cat")
        if cat not in _CATEGORY_STOP_WORDS:
            return cat
    return None


def extract_all(text: str) -> dict[str, Any]:
    """执行全部粗实体抽取，合并结果。"""
    entities: dict[str, Any] = {}
    entities.update(extract_price_entities(text))

    qty = extract_quantity(text)
    if qty is not None:
        entities["quantity"] = qty

    order_ref = extract_order_reference(text)
    if order_ref is not None:
        entities["order_ref"] = order_ref

    cat = extract_category_hint(text)
    if cat is not None:
        entities["raw_category_text"] = cat

    return entities
