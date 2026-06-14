"""场景识别常量 — 路由/Skill/Intent 字符串常量。

从旧 intent/classifier_types.py 迁移至此。
"""

from __future__ import annotations

from typing import Literal

# ── 路由类型常量 ──
ROUTE_SILENT: RouteType = "SILENT"
ROUTE_GENERAL_REPLY: RouteType = "GENERAL_REPLY"
ROUTE_AGENT: RouteType = "AGENT"
ROUTE_HUMAN: RouteType = "HUMAN"

RouteType = Literal["SILENT", "GENERAL_REPLY", "AGENT", "HUMAN"]
ROUTE_TYPES = {ROUTE_SILENT, ROUTE_GENERAL_REPLY, ROUTE_AGENT, ROUTE_HUMAN}

# ── 意图 skill 常量（intent → skill_registry 映射用）──
SKILL_HUMAN_SERVICE = "human_service"
SKILL_PRODUCT_PRICE = "product_price"
SKILL_PRODUCT_STOCK = "product_stock"
SKILL_DELIVERY_TIME = "delivery_time"
SKILL_ORDER_STATUS = "order_status"
SKILL_LOGISTICS_STATUS = "logistics_status"
SKILL_INVOICE = "invoice"
SKILL_SEARCH_PRODUCTS = "search_products"
SKILL_GENERAL_REPLY = "general_reply"
SKILL_CREATE_ORDER = "create_order"
SKILL_CONFIRM_ORDER = "confirm_order"
SKILL_DISCOUNT_REQUEST = "discount_request"
SKILL_REMEMBER_INFO = "remember_info"

# ── 意图名常量（DEFAULT_INTENT_ROUTE_MAP 的 key）──
INTENT_TRANSFER_REQUEST = "transfer_request"
INTENT_COMPLAINT = "complaint"
INTENT_ABUSE = "abuse"
INTENT_LEGAL_THREAT = "legal_threat"
INTENT_UNSUBSCRIBE = "unsubscribe"
INTENT_EXIT = "exit"
INTENT_CANCEL = "cancel"
INTENT_DELETE_ACCOUNT = "delete_account"
INTENT_RETURN_REFUND = "return_refund"
INTENT_PRODUCT_PRICE = "product_price"
INTENT_PRODUCT_STOCK = "product_stock"
INTENT_DELIVERY_TIME = "delivery_time"
INTENT_ORDER_STATUS = "order_status"
INTENT_LOGISTICS_STATUS = "logistics_status"
INTENT_INVOICE = "invoice"
INTENT_PRODUCT_SEARCH = "product_search"
INTENT_PRODUCT_INQUIRY = "product_inquiry"
INTENT_UNKNOWN = "unknown_intent"
INTENT_CHITCHAT = "chitchat"
INTENT_SILENT_EMPTY = "silent_empty"
INTENT_SILENT_NOISE = "silent_noise"
INTENT_SILENT_ACK = "silent_ack"
INTENT_SILENT_THANKS = "silent_thanks"
INTENT_PLACE_ORDER = "place_order"
INTENT_CONFIRM_ORDER = "confirm_order"
INTENT_DISCOUNT_REQUEST = "discount_request"
INTENT_PROMOTION_INQUIRY = "promotion_inquiry"
INTENT_PAYMENT_INQUIRY = "payment_inquiry"
INTENT_SAVE_PREFERENCE = "save_preference"
