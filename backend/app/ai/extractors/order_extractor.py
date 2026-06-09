"""订单相关确定性参数抽取器。"""

from __future__ import annotations

import re
from typing import Any


# 15~20 位 Snowflake 订单号，避免误匹配普通手机号。
ORDER_ID_PATTERN = re.compile(r"(?<!\d)(\d{15,20})(?!\d)")
PHONE_PATTERN = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
QUANTITY_PATTERN = re.compile(r"(\d+)\s*(?:件|个|盒|瓶|箱|包|袋|斤|克|kg|KG|份|套)")
CHINESE_QUANTITY_PATTERN = re.compile(r"(一|二|两|三|四|五|六|七|八|九|十)\s*(?:瓶|件|个|盒|箱|包|袋|斤|份|套)")
PRICE_PATTERN_FOR_CLEANUP = re.compile(
    r"(?:报价|报|出价|给|便宜到|优惠到|最低|降到|改成|价格)\s*[¥￥]?\s*(\d+(?:\.\d{1,2})?)\s*(?:元|块|rmb|RMB)?"
    r"|[¥￥]\s*(\d+(?:\.\d{1,2})?)"
    r"|(\d+(?:\.\d{1,2})?)\s*(?:元|块|rmb|RMB)"
)

CHINESE_DIGITS = {
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

ADDRESS_HINTS = ("地址", "收货", "寄到", "送到", "发到")
CREATE_ORDER_WORDS = ("下单", "买", "来", "要", "拍", "订")
ORDER_ACTION_WORDS = {
    "update_address": ("改地址", "修改地址", "换地址", "地址改", "地址换"),
    "add_note": ("备注", "加备注", "添加备注"),
}


def extract_order_id(text: str) -> int | None:
    """抽取 15~20 位订单号。"""

    match = ORDER_ID_PATTERN.search(text)
    return int(match.group(1)) if match else None


def extract_phone(text: str) -> str | None:
    """抽取中国大陆手机号。"""

    match = PHONE_PATTERN.search(text)
    return match.group(1) if match else None


def extract_quantity(text: str) -> int:
    """抽取固定数量，默认 1。"""

    match = QUANTITY_PATTERN.search(text)
    if match:
        try:
            return max(int(match.group(1)), 1)
        except ValueError:
            return 1
    chinese_match = CHINESE_QUANTITY_PATTERN.search(text)
    if chinese_match:
        return CHINESE_DIGITS.get(chinese_match.group(1), 1)
    return 1


def extract_quantity_delta(text: str) -> int | None:
    """抽取数量增减，例如加一个或少一个。"""

    increment_words = ("再来", "再加", "多买", "加一个", "加一件", "加1个", "加1件")
    decrement_words = ("少一个", "少一件", "少1个", "少1件", "减一个", "减一件", "减1个", "减1件")
    if any(word in text for word in increment_words):
        return extract_quantity(text)
    if any(word in text for word in decrement_words):
        return -extract_quantity(text)
    return None


def extract_order_action(text: str) -> str:
    """将客户话术映射为订单操作类型。"""

    for action, words in ORDER_ACTION_WORDS.items():
        if any(word in text for word in words):
            return action
    return "query"


def extract_address(text: str) -> str | None:
    """在地址提示词后抽取收货地址，并移除其中的手机号。"""

    for hint in ADDRESS_HINTS:
        if hint not in text:
            continue
        tail = text.split(hint, 1)[1].strip(" :：，,。")
        if tail:
            phone = extract_phone(tail)
            if phone:
                tail = tail.replace(phone, "").strip(" :：，,。")
            return tail or None
    return None


def extract_product_phrase(text: str) -> str | None:
    """从订单类客户话术中识别商品名称片段。"""

    cleaned = text.strip()
    for token in ("，", ",", "。", "；", ";"):
        cleaned = cleaned.replace(token, " ")

    matched_order_word = False
    for word in CREATE_ORDER_WORDS:
        if word in cleaned:
            matched_order_word = True
            tail = cleaned.split(word, 1)[1].strip()
            phrase = _strip_non_product_parts(tail)
            if phrase:
                return phrase

    if matched_order_word:
        return None

    phrase = _strip_non_product_parts(cleaned)
    return phrase or None


def extract_create_order_args(args: dict[str, Any], text: str) -> dict[str, Any]:
    """抽取创建订单所需的商品、数量、电话和地址。"""

    extracted: dict[str, Any] = {}
    if not args.get("items"):
        product_name = extract_product_phrase(text)
        if product_name:
            extracted["items"] = [{
                "product_name": product_name,
                "quantity": extract_quantity(text),
                "quantity_explicit": has_quantity(text),
            }]
    phone = args.get("receiver_phone") or extract_phone(text)
    if phone:
        extracted["receiver_phone"] = phone
    address = args.get("shipping_address") or extract_address(text)
    if address:
        extracted["shipping_address"] = address
    return extracted


def has_quantity(text: str) -> bool:
    return QUANTITY_PATTERN.search(text) is not None or CHINESE_QUANTITY_PATTERN.search(text) is not None


def _strip_non_product_parts(text: str) -> str:
    text = PHONE_PATTERN.sub("", text)
    text = ORDER_ID_PATTERN.sub("", text)
    text = PRICE_PATTERN_FOR_CLEANUP.sub("", text)
    text = re.sub(r"\d+\s*(?:件|个|盒|瓶|箱|包|袋|斤|克|kg|KG|份|套)", "", text)
    text = CHINESE_QUANTITY_PATTERN.sub("", text)
    for label in ("电话", "手机号", "手机", "联系方式", "联系"):
        if label in text:
            text = text.split(label, 1)[0]
    for hint in ADDRESS_HINTS:
        if hint in text:
            text = text.split(hint, 1)[0]
    for word in ("吧", "呀", "呢", "啊", "吗", "么", "多少钱", "有货", "库存", "发货", "今天能发", "确认订单"):
        text = text.replace(word, "")
    return text.strip(" :：，,。！？!?")


ORDER_EXTRACTORS = {
    "confirm_order": {
        "order_id": extract_order_id,
    },
    "manage_order": {
        "order_id": extract_order_id,
        "action": extract_order_action,
    },
    "create_order": {
        "__composite__": extract_create_order_args,
    },
    "create_order_draft": {
        "__composite__": extract_create_order_args,
    },
    "update_order_draft": {
        "order_id": extract_order_id,
        "receiver_phone": extract_phone,
        "shipping_address": extract_address,
        "quantity": extract_quantity,
        "product_name": extract_product_phrase,
    },
    "update_draft_order_quantity": {
        "order_id": extract_order_id,
        "quantity": extract_quantity,
        "quantity_delta": extract_quantity_delta,
        "product_name": extract_product_phrase,
    },
}
