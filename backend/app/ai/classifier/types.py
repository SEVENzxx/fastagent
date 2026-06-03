"""意图识别与路由的共享数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# ── 路由类型常量 ──
ROUTE_SILENT: RouteType = "SILENT"
ROUTE_GENERAL_REPLY: RouteType = "GENERAL_REPLY"
ROUTE_AGENT: RouteType = "AGENT"
ROUTE_HUMAN: RouteType = "HUMAN"

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

RouteType = Literal["SILENT", "GENERAL_REPLY", "AGENT", "HUMAN"]
ROUTE_TYPES = {ROUTE_SILENT, ROUTE_GENERAL_REPLY, ROUTE_AGENT, ROUTE_HUMAN}


@dataclass(frozen=True, slots=True)
class IntentCandidate:
    """向量、关键词或融合层产生的候选意图。"""

    intent: str
    label: str
    score: float
    source: str
    matched_text: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class IntentHit:
    """单个 segment 的最终意图命中结果。"""

    segment: str
    intent: str
    label: str
    confidence: float
    route: RouteType
    skill: str | None = None
    candidates: list[IntentCandidate] = field(default_factory=list)
    ambiguous: bool = False
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class IntentResult:
    """完整意图识别结果。"""

    original_text: str
    normalized_text: str
    primary_intent: str | None
    confidence: float
    hits: list[IntentHit] = field(default_factory=list)
    candidates: list[IntentCandidate] = field(default_factory=list)
    is_multi_intent: bool = False
    need_clarification: bool = False
    source: str = "unknown"
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RoutedIntent:
    """最终路由结果，作为 MessageRouter/Executor 的输入。"""

    primary_intent: str | None
    confidence: float
    route: RouteType
    skill: str | None = None
    hits: list[IntentHit] = field(default_factory=list)
    is_multi_intent: bool = False
    need_clarification: bool = False
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class KeywordEntityResult:
    """关键词/实体层输出的辅助信号。"""

    keywords: list[str] = field(default_factory=list)
    entities: dict[str, list[str]] = field(default_factory=dict)
    intent_boosts: dict[str, float] = field(default_factory=dict)
    risk_flags: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PendingIntentState:
    """会话中等待用户补充的意图状态。

    例如：
    - intent=order_status
    - skill=order_status
    - required_entities=["order_no"]
    - filled_entities={}

    当用户下一轮只输入一串订单号时，ContextStateResolver 会优先把它识别为
    上一轮任务的槽位补全，而不是重新当作一条新问题做向量召回。
    """

    intent: str
    skill: str | None
    required_entities: list[str] = field(default_factory=list)
    filled_entities: dict[str, str] = field(default_factory=dict)
    last_prompt: str | None = None
    created_at: str | None = None
