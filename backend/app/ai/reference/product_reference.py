"""统一商品引用解析。"""

from __future__ import annotations

import inspect
import logging
import re
from difflib import SequenceMatcher
from collections.abc import Awaitable, Callable
from typing import Any

from app.ai.memory.conversation_state import ConversationCommerceState
from app.ai.schemas.commerce_types import ProductReferenceResult

GlobalProductSearch = Callable[[str], dict[str, Any] | None | Awaitable[dict[str, Any] | None]]

CHINESE_NUMBERS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

REFERENCE_WORDS = ("这个", "这款", "就这个", "刚才那个", "上面那个", "那个", "它")
SELECTION_INDEX_PATTERN = re.compile(r"第([一二两三四五六七八九十\d]+)(?:款|个|件|条)?")

logger = logging.getLogger(__name__)

PRODUCT_STOP_WORDS = (
    "给我",
    "帮我",
    "一下",
    "看一下",
    "看看",
    "看下",
    "详细介绍一下",
    "详细介绍",
    "详细",
    "介绍一下",
    "介绍",
    "怎么样",
    "如何",
    "适合",
    "合适",
    "好用",
    "库存",
    "还有多少",
    "多少钱",
    "价格",
    "有货",
    "买",
    "下单",
    "购买",
    "我要",
    "要",
    "来",
    "订",
    "拍",
    "一个",
    "两个",
    "一件",
    "两件",
    "吧",
    "吗",
    "呢",
    "？",
    "?",
)

async def resolve_product_reference(
    user_message: str,
    context: ConversationCommerceState,
    *,
    global_search: GlobalProductSearch | None = None,
) -> ProductReferenceResult:
    """解析用户指的是哪一个商品或服务。"""
    text = user_message.strip()
    pending_candidates = _pending_candidates(context)

    selection_index = parse_selection_index(text)
    if selection_index is not None:
        if 0 <= selection_index < len(pending_candidates):
            product = pending_candidates[selection_index]
            logger.info("商品引用命中序号：index=%s product=%s", selection_index + 1, product.get("name"))
            return _matched(product, source="pending_candidates_index", confidence=1.0, reason="matched explicit candidate index")
        logger.info("商品引用序号越界：index=%s candidates=%s", selection_index + 1, len(pending_candidates))
        return ProductReferenceResult(matched=False, reason="candidate index out of range")

    if _has_deictic_reference(text):
        product = _selected_or_last_product(context, pending_candidates)
        if product is not None:
            source = "selected_product" if _selected_product(context) is not None else "last_product"
            logger.info("商品引用命中指代：source=%s product=%s", source, product.get("name"))
            return _matched(product, source=source, confidence=0.9, reason="matched deictic reference")

    query = normalize_product_reference_text(text)
    candidate_matches = match_products_from_candidates(query, pending_candidates)
    if len(candidate_matches) == 1:
        logger.info("商品引用命中候选名称：query=%s product=%s", query, candidate_matches[0].get("name"))
        return _matched(
            candidate_matches[0],
            source="pending_candidates_name",
            confidence=0.86,
            reason="matched pending candidate name",
        )
    if len(candidate_matches) > 1:
        logger.info("商品引用候选歧义：query=%s candidates=%s", query, len(candidate_matches))
        return ProductReferenceResult(
            matched=False,
            ambiguous=True,
            candidates=candidate_matches,
            confidence=0.6,
            reason="multiple pending candidates matched",
        )

    if global_search is not None and _has_possible_product_keyword(text):
        product = global_search(text)
        if inspect.isawaitable(product):
            product = await product
        if product is not None:
            logger.info("商品引用命中全局搜索：product=%s", product.get("name"))
            return _matched(product, source="global_search", confidence=0.72, reason="matched global product search")

    logger.info("商品引用未命中：query=%s candidates=%s", query, len(pending_candidates))
    return ProductReferenceResult(matched=False, reason="no product reference matched")


def parse_selection_index(text: str) -> int | None:
    """从"第一款""第1款"或"1"提取候选序号。"""
    stripped = text.strip(" :：，,。！!?？")
    if stripped.isdigit():
        return int(stripped) - 1
    normalized = normalize_product_reference_text(stripped)
    if normalized.isdigit():
        return int(normalized) - 1

    match = SELECTION_INDEX_PATTERN.search(text)
    if match:
        number = parse_chinese_or_arabic_number(match.group(1))
        return number - 1 if number is not None else None
    return None


def parse_selection_indices(text: str) -> list[int]:
    """提取文本中的多个候选序号。"""
    indices: list[int] = []
    for match in SELECTION_INDEX_PATTERN.finditer(text):
        number = parse_chinese_or_arabic_number(match.group(1))
        if number is not None:
            indices.append(number - 1)
    return indices


def parse_chinese_or_arabic_number(value: str) -> int | None:
    value = value.strip()
    if value.isdigit():
        return int(value)
    return CHINESE_NUMBERS.get(value)


def normalize_product_reference_text(text: str) -> str:
    cleaned = text.lower()
    for word in PRODUCT_STOP_WORDS + REFERENCE_WORDS:
        cleaned = cleaned.replace(word.lower(), "")
    normalized = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", cleaned)
    return normalized


def match_products_from_candidates(query: str, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not query:
        return []
    matches: list[dict[str, Any]] = []
    for product in products:
        aliases = product_reference_aliases(product)
        if aliases and any(query == alias or query in alias for alias in aliases):
            matches.append(product)
            continue
        if _has_ascii(query) and aliases and max((_similarity(query, alias) for alias in aliases), default=0.0) >= 0.78:
            matches.append(product)
    return matches


def product_reference_aliases(product: dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    for value in (product.get("name"), product.get("sku")):
        normalized = normalize_product_reference_text(str(value or ""))
        if normalized:
            aliases.add(normalized)
            aliases.update(_compact_english_number_aliases(normalized))

    raw_name = str(product.get("name") or "")
    for token in re.split(r"[\s,，/／\-_\(\)（）]+", raw_name):
        normalized = normalize_product_reference_text(token)
        if normalized:
            aliases.add(normalized)
            aliases.update(_compact_english_number_aliases(normalized))
            aliases.update(_chinese_sub_phrases(normalized))
    return aliases


def _pending_candidates(context: ConversationCommerceState) -> list[dict[str, Any]]:
    # 用户明确看到过的编号列表优先；内部检索候选不能覆盖它，避免"1呢？"选错对象。
    candidates = (
        context.last_displayed_candidates
        or context.pending_candidates
        or context.disambiguation_candidates
        or context.last_recommended_products
    )
    return [dict(item) for item in candidates if isinstance(item, dict)]


def _selected_product(context: ConversationCommerceState) -> dict[str, Any] | None:
    selected = context.selected_product
    return dict(selected) if isinstance(selected, dict) else None


def _selected_or_last_product(context: ConversationCommerceState, pending_candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    selected = _selected_product(context)
    if selected is not None:
        return selected

    selected_product_id = context.selected_product_id
    last_product_id = context.last_product_id
    for product_id in (selected_product_id, last_product_id):
        if product_id is None:
            continue
        match = next((item for item in pending_candidates if str(item.get("id")) == str(product_id)), None)
        if match is not None:
            return match

    if len(pending_candidates) == 1:
        return pending_candidates[0]
    return None


def _has_deictic_reference(text: str) -> bool:
    return any(word in text for word in REFERENCE_WORDS)


def _has_possible_product_keyword(text: str) -> bool:
    return bool(normalize_product_reference_text(text))


def _matched(
    product: dict[str, Any],
    *,
    source: str,
    confidence: float,
    reason: str,
) -> ProductReferenceResult:
    product_payload = dict(product)
    product_id = product_payload.get("id")
    product_name = product_payload.get("name")
    return ProductReferenceResult(
        matched=True,
        product_id=str(product_id) if product_id is not None else None,
        product_name=str(product_name) if product_name is not None else None,
        source=source,  # type: ignore[arg-type]
        confidence=confidence,
        candidates=[product_payload],
        reason=reason,
    )


def _chinese_sub_phrases(value: str) -> set[str]:
    if not re.fullmatch(r"[\u4e00-\u9fff]+", value):
        return set()
    phrases: set[str] = set()
    for size in range(2, min(len(value), 8) + 1):
        for start in range(0, len(value) - size + 1):
            phrases.add(value[start:start + size])
    return phrases


def _compact_english_number_aliases(value: str) -> set[str]:
    aliases: set[str] = set()
    compact = re.sub(r"[^0-9a-zA-Z]+", "", value.lower())
    if compact:
        aliases.add(compact)
    return aliases


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left.lower(), right.lower()).ratio()


def _has_ascii(value: str) -> bool:
    return bool(re.search(r"[0-9a-zA-Z]", value))
