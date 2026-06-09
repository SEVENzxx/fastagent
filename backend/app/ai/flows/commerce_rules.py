"""规则优先的电商路由。"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.ai.memory.conversation_state import ConversationCommerceState
from app.ai.reference.product_reference import (
    match_products_from_candidates,
    normalize_product_reference_text,
    parse_selection_index,
    parse_selection_indices,
)
from app.ai.schemas.commerce_types import CommerceRoute, DecisionResult, RiskLevel, SlotResult, ActionType, SkillName, \
    ResponseType

PHONE_PATTERN = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
ORDER_ID_PATTERN = re.compile(r"\b(\d{15,20})\b")

CHINESE_QUANTITIES = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
ARABIC_QUANTITY_PATTERNS = (
    re.compile(r"(?:买|要|下单|来|订|拍|数量(?:改成|改为)?|改成)\s*(\d{1,2})\s*(?:件|个|台|部|盒|瓶|箱|包|袋|份|套)?"),
    re.compile(r"(\d{1,2})\s*(?:件|个|台|部|盒|瓶|箱|包|袋|份|套)"),
)
CHINESE_QUANTITY_PATTERN = re.compile(r"(?:买|要|下单|来|订|拍|数量(?:改成|改为)?|改成)?\s*(一|二|两|三|四|五|六|七|八|九|十)\s*(?:件|个|台|部|盒|瓶|箱|包|袋|份|套)?")

CANCEL_WORDS = ("取消订单", "取消", "不要了", "算了", "不买了", "先不买", "放弃")
CONFIRM_WORDS = ("确认下单", "确认", "就这样", "可以下单", "没问题", "就这么定")
BUY_WORDS = ("买这个", "买这款", "我要这个", "我要这款", "我要买", "帮我下单", "下单", "就买", "给我下单", "买一个", "买一件")
ORDER_QUERY_WORDS = ("查订单", "查一下我的订单", "订单到哪", "订单状态", "我的订单", "有哪些订单", "看看我有哪些订单", "查看订单", "查看已取消的订单", "已取消的订单")
ADDRESS_WORDS = ("地址", "收货地址", "收货", "寄到", "送到", "发到")
PHONE_WORDS = ("电话", "联系电话", "手机号", "手机")
INCREMENT_WORDS = ("再来", "再加", "多买", "加一个", "加一件", "加1个", "加1件")
DECREMENT_WORDS = ("少一个", "少一件", "少1个", "少1件", "减一个", "减一件", "减1个", "减1件")
QUANTITY_UPDATE_WORDS = ("改成", "改为", "改数量", "修改数量", "数量")

PRODUCT_LIST_WORDS = ("有什么", "有哪些", "有啥", "推荐", "看看", "看下", "给我看看", "哪几款", "有没有")
PRODUCT_DETAIL_WORDS = ("详细介绍", "介绍一下", "介绍下", "怎么样", "如何", "适合", "合适", "好用", "库存", "价格", "多少钱", "有货", "咨询")
PRODUCT_COMPARE_WORDS = ("区别", "对比", "比一比", "比较")
EXIT_WORDS = ("退出", "退出当前流程", "先不看了", "不看了", "结束选择")

logger = logging.getLogger(__name__)


def route_commerce_message(text: str, context: ConversationCommerceState | None = None) -> tuple[DecisionResult, SlotResult]:
    """电商规则路由：按优先级逐条匹配关键词 / 槽位，0 LLM 调用。

    Args:
        text: 用户输入原文
        context: 会话状态（读取草稿、候选商品等上下文）

    Returns:
        (决策结果, 抽取槽位)
    """
    message = text.strip()                          # 原始输入
    slots = extract_slots(message)                  # 抽取数量/地址/电话/订单号等槽位
    has_draft = bool((context.draft_order_id or context.pending_order_id) if context else None)

    # ── 规则 1：退出词（"不看了""算了"）→ 退出流程 ──
    if message in EXIT_WORDS:
        logger.info("规则路由命中：route=FALLBACK action=exit_flow")
        return (
            DecisionResult(
                route=CommerceRoute.FALLBACK,
                action_type=ActionType.EXIT_FLOW,
                response_type=ResponseType.FLOW_EXIT,
                risk_level=RiskLevel.READ_ONLY,
                reason="matched exit flow rule",
            ),
            slots,
        )

    # ── 规则 2：查订单（关键词 / 提取到订单号）→ 优先于取消词 ──
    if _contains_any(message, ORDER_QUERY_WORDS) or slots.order_id:
        logger.info("规则路由命中：route=ORDER_ACTION action=query_order order_id=%s", slots.order_id)
        status_filter = "cancelled" if "已取消" in message or "取消的订单" in message else None
        return (
            DecisionResult(
                route=CommerceRoute.ORDER_ACTION,
                action_type=ActionType.QUERY_ORDER,
                skill_name=SkillName.MANAGE_ORDER,
                response_type=ResponseType.ORDER_QUERY_RESULT,
                risk_level=RiskLevel.READ_ONLY,
                reason="matched order query rule",
                skill_params={"status": status_filter} if status_filter else {},
            ),
            slots,
        )

    # ── 规则 3：取消 + 有草稿 → 取消草稿订单 ──
    if _contains_any(message, CANCEL_WORDS) and has_draft:
        logger.info("规则路由命中：route=ORDER_ACTION action=cancel_order reason=cancel")
        return (
            DecisionResult(
                route=CommerceRoute.ORDER_ACTION,
                action_type=ActionType.CANCEL_ORDER,
                skill_name=SkillName.CANCEL_ORDER_DRAFT,
                response_type=ResponseType.ORDER_CANCELLED,
                risk_level=RiskLevel.HIGH_RISK_WRITE,
                reason="matched cancel rule",
            ),
            slots.model_copy(update={"cancel_flag": True}),
        )

    # ── 规则 4：取消 + 无草稿 → 退出流程（清理上下文）──
    if _contains_any(message, CANCEL_WORDS):
        logger.info("规则路由命中：route=FALLBACK action=exit_flow reason=cancel_without_draft")
        return (
            DecisionResult(
                route=CommerceRoute.FALLBACK,
                action_type=ActionType.EXIT_FLOW,
                response_type=ResponseType.FLOW_EXIT,
                risk_level=RiskLevel.READ_ONLY,
                reason="cancel words without draft exits current selection",
            ),
            slots,
        )

    # ── 规则 5：确认下单 → 高风险写操作 ──
    if _contains_any(message, CONFIRM_WORDS):
        logger.info("规则路由命中：route=ORDER_ACTION action=confirm_order reason=confirm")
        return (
            DecisionResult(
                route=CommerceRoute.ORDER_ACTION,
                action_type=ActionType.CONFIRM_ORDER,
                skill_name=SkillName.CONFIRM_ORDER,
                response_type=ResponseType.ORDER_CONFIRMED,
                risk_level=RiskLevel.HIGH_RISK_WRITE,
                reason="matched confirm rule",
            ),
            slots.model_copy(update={"confirm_flag": True}),
        )

    # ── 规则 6：有草稿 + 提取到数量 → 修改草稿数量 ──
    if has_draft and (slots.quantity is not None or slots.quantity_delta is not None):
        logger.info("规则路由命中：route=ORDER_ACTION action=update_quantity draft=true")
        return (
            DecisionResult(
                route=CommerceRoute.ORDER_ACTION,
                action_type=ActionType.UPDATE_QUANTITY,
                skill_name=SkillName.UPDATE_DRAFT_ORDER_QUANTITY,
                response_type=ResponseType.DRAFT_ORDER_UPDATED,
                risk_level=RiskLevel.LOW_RISK_WRITE,
                reason="matched quantity update while draft exists",
            ),
            slots,
        )

    # ── 规则 7：提取到地址/电话 → 补全联系方式 ──
    if slots.address or slots.phone:
        logger.info(
            "规则路由命中：route=ORDER_ACTION action=update_contact has_address=%s has_phone=%s",
            bool(slots.address),
            bool(slots.phone),
        )
        return (
            DecisionResult(
                route=CommerceRoute.ORDER_ACTION,
                action_type=ActionType.UPDATE_CONTACT,
                skill_name=SkillName.UPDATE_ORDER_DRAFT if has_draft else None,
                response_type=ResponseType.DRAFT_ORDER_UPDATED if has_draft else ResponseType.MISSING_SLOTS,
                risk_level=RiskLevel.LOW_RISK_WRITE,
                reason="matched address/phone rule",
            ),
            slots,
        )

    # ── 规则 8：草稿待补信息 + 地址类文本 → 自动填入地址 ──
    if has_draft and _current_stage(context) == "ORDER_PENDING_INFO" and _looks_like_address_only(message):
        logger.info("规则路由命中：route=ORDER_ACTION action=update_contact reason=address_like")
        return (
            DecisionResult(
                route=CommerceRoute.ORDER_ACTION,
                action_type=ActionType.UPDATE_CONTACT,
                skill_name=SkillName.UPDATE_ORDER_DRAFT,
                response_type=ResponseType.DRAFT_ORDER_UPDATED,
                risk_level=RiskLevel.LOW_RISK_WRITE,
                reason="pending draft treats address-like text as contact update",
            ),
            slots.model_copy(update={"address": message}),
        )

    # ── 规则 9：购买意图（"买"/"下单"/"要这个"）→ 创建订单草稿 ──
    if _contains_any(message, BUY_WORDS) or _looks_like_purchase(message):
        logger.info("规则路由命中：route=ORDER_ACTION action=create_draft_order")
        return (
            DecisionResult(
                route=CommerceRoute.ORDER_ACTION,
                action_type=ActionType.CREATE_DRAFT_ORDER,
                skill_name=SkillName.CREATE_ORDER_DRAFT,
                response_type=ResponseType.DRAFT_ORDER_CREATED,
                risk_level=RiskLevel.LOW_RISK_WRITE,
                reason="matched buy rule",
            ),
            slots,
        )

    # ── 规则 10：商品对比（"区别"/"哪个好"/两个序号）→ 对比咨询 ──
    if _looks_like_compare(message):
        logger.info("规则路由命中：route=PRODUCT_CONSULT action=compare_products")
        return (
            DecisionResult(
                route=CommerceRoute.PRODUCT_CONSULT,
                action_type=ActionType.COMPARE_PRODUCTS,
                response_type=ResponseType.PRODUCT_COMPARE,
                risk_level=RiskLevel.READ_ONLY,
                reason="matched product compare rule",
            ),
            slots,
        )

    # ── 规则 11：商品关键词 / 序号 → 商品咨询 ──
    if _contains_any(message, PRODUCT_LIST_WORDS + PRODUCT_DETAIL_WORDS) or parse_selection_index(message) is not None:
        logger.info("规则路由命中：route=PRODUCT_CONSULT action=consult_product")
        return (
            DecisionResult(
                route=CommerceRoute.PRODUCT_CONSULT,
                action_type=ActionType.CONSULT_PRODUCT,
                response_type=ResponseType.PRODUCT_KNOWLEDGE_ANSWER,
                risk_level=RiskLevel.READ_ONLY,
                reason="matched product consult rule",
            ),
            slots,
        )

    # ── 规则 12：待选商品名命中 → 商品咨询（指代兜底）──
    if _matches_pending_candidate(message, context):
        logger.info("规则路由命中：route=PRODUCT_CONSULT action=consult_product reason=pending_candidate")
        return (
            DecisionResult(
                route=CommerceRoute.PRODUCT_CONSULT,
                action_type=ActionType.CONSULT_PRODUCT,
                response_type=ResponseType.PRODUCT_KNOWLEDGE_ANSWER,
                risk_level=RiskLevel.READ_ONLY,
                reason="matched pending candidate reference",
            ),
            slots,
        )

    # ── 规则 13：全部未命中 → 交给通用意图识别 + RAG 管线 ──
    logger.info("规则路由未命中：route=GENERAL_RAG")
    return (
        DecisionResult(
            route=CommerceRoute.GENERAL_RAG,
            response_type=ResponseType.FALLBACK,
            risk_level=RiskLevel.READ_ONLY
        ),
        slots,
    )


def extract_slots(text: str) -> SlotResult:
    quantity, quantity_delta = _extract_quantity_update(text)
    phone = _extract_phone(text)
    address = _extract_address(text)
    order_id = _extract_order_id(text)
    return SlotResult(
        quantity=quantity,
        quantity_delta=quantity_delta,
        address=address,
        phone=phone,
        selection_index=parse_selection_index(text),
        order_id=order_id,
        product_keyword=_strip_action_words(text),
    )


def _extract_phone(text: str) -> str | None:
    match = PHONE_PATTERN.search(text)
    return match.group(1) if match else None


def _extract_order_id(text: str) -> str | None:
    match = ORDER_ID_PATTERN.search(text)
    return match.group(1) if match else None


def _extract_address(text: str) -> str | None:
    for hint in ADDRESS_WORDS:
        if hint not in text:
            continue
        tail = text.split(hint, 1)[1].strip(" :：，,。")
        if not tail:
            continue
        tail = re.split(r"(?:电话|手机号|手机|联系方式|联系)", tail, maxsplit=1)[0].strip(" :：，,。")
        phone = PHONE_PATTERN.search(tail)
        if phone:
            tail = tail.replace(phone.group(1), "").strip(" :：，,。")
        return tail or None
    return None


def _extract_quantity_update(text: str) -> tuple[int | None, int | None]:
    quantity = _extract_quantity(text)
    if _contains_any(text, INCREMENT_WORDS):
        return None, quantity or 1
    if _contains_any(text, DECREMENT_WORDS):
        return None, -(quantity or 1)
    if quantity is not None:
        return quantity, None
    return None, None


def _extract_quantity(text: str) -> int | None:
    for char, value in CHINESE_QUANTITIES.items():
        if f"{char}个" in text or f"{char}台" in text or f"{char}部" in text or f"{char}件" in text:
            return value
    for pattern in ARABIC_QUANTITY_PATTERNS:
        match = pattern.search(text)
        if match:
            return max(int(match.group(1)), 1)
    match = CHINESE_QUANTITY_PATTERN.search(text)
    if match:
        return CHINESE_QUANTITIES.get(match.group(1))
    return None


def _strip_action_words(text: str) -> str:
    cleaned = text
    for word in (
        CANCEL_WORDS
        + CONFIRM_WORDS
        + BUY_WORDS
        + ORDER_QUERY_WORDS
        + ADDRESS_WORDS
        + PHONE_WORDS
        + QUANTITY_UPDATE_WORDS
        + PRODUCT_LIST_WORDS
        + PRODUCT_DETAIL_WORDS
    ):
        cleaned = cleaned.replace(word, "")
    cleaned = PHONE_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", cleaned)
    return cleaned or None  # type: ignore[return-value]


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def _looks_like_purchase(text: str) -> bool:
    if "买" not in text and "要" not in text:
        return False
    if any(word in text for word in ("不买", "不要", "取消")):
        return False
    return bool(parse_selection_index(text) is not None or _extract_quantity(text) is not None or "这款" in text or "这个" in text)


def _looks_like_compare(text: str) -> bool:
    if len(parse_selection_indices(text)) >= 2:
        return True
    if any(word in text for word in ("哪一个", "哪个好", "哪款好", "好一些", "更好", "更适合")) and any(
        marker in text for marker in ("和", "与", "、")
    ):
        return True
    if "比较好" in text or "推荐" in text:
        return False
    return _contains_any(text, PRODUCT_COMPARE_WORDS)


def _current_stage(context: ConversationCommerceState | None) -> str | None:
    """从上下文读取当前阶段值（枚举转字符串）。"""
    if context is None:
        return None
    return context.stage.value


def _looks_like_address_only(text: str) -> bool:
    if len(text.strip()) < 3:
        return False
    if any(word in text for word in PRODUCT_DETAIL_WORDS + BUY_WORDS + CANCEL_WORDS + CONFIRM_WORDS):
        return False
    if PHONE_PATTERN.search(text):
        return True
    return any(marker in text for marker in ("省", "市", "区", "县", "镇", "乡", "街道", "路", "号", "小区", "成都", "上海", "北京", "广州", "深圳"))


def _matches_pending_candidate(text: str, context: ConversationCommerceState | None) -> bool:
    if context is None:
        return False
    candidates = context.pending_candidates or context.last_recommended_products
    products = [dict(item) for item in candidates if isinstance(item, dict)]
    if not products:
        return False
    query = normalize_product_reference_text(text)
    return bool(match_products_from_candidates(query, products))
