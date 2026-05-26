"""Phase 8 意图识别配置。

当前先使用代码内配置，后续可以替换为 YAML/DB/管理后台。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.ai.intent.types import RouteType


@dataclass(frozen=True, slots=True)
class StrongRuleConfig:
    """强规则配置。"""

    intent: str
    label: str
    keywords: tuple[str, ...]
    route: RouteType
    skill: str | None = None
    confidence: float = 1.0
    should_stop: bool = True
    reason: str = ""


@dataclass(frozen=True, slots=True)
class KeywordBoostConfig:
    """关键词到 intent 的加权配置。"""

    keyword: str
    intent: str
    boost: float
    reason: str = ""


@dataclass(frozen=True, slots=True)
class IntentRouteConfig:
    """intent 到 route/skill 的映射配置。"""

    route: RouteType
    skill: str | None = None
    label: str = ""


@dataclass(frozen=True, slots=True)
class IntentRecognitionConfig:
    """意图识别主配置。"""

    vector_top_k: int = 20
    vector_min_score: float = 0.75
    high_confidence_score: float = 0.86
    ambiguous_gap: float = 0.05
    enable_llm_fallback: bool = True
    enable_multi_intent: bool = True
    rules: tuple[StrongRuleConfig, ...] = field(default_factory=tuple)
    keyword_boosts: tuple[KeywordBoostConfig, ...] = field(default_factory=tuple)
    intent_route_map: dict[str, IntentRouteConfig] = field(default_factory=dict)

    def route_for(self, intent: str) -> IntentRouteConfig:
        """返回 intent 路由配置；未知意图默认走 GENERAL_REPLY。"""
        return self.intent_route_map.get(intent, self.intent_route_map["unknown_intent"])

    def label_for(self, intent: str) -> str:
        """返回 intent 展示标签；未知时返回原始 intent。"""
        route = self.intent_route_map.get(intent)
        return route.label if route and route.label else intent


DEFAULT_INTENT_ROUTE_MAP: dict[str, IntentRouteConfig] = {
    "transfer_request": IntentRouteConfig("HUMAN", "human_service", "转人工"),
    "complaint": IntentRouteConfig("HUMAN", "human_service", "投诉"),
    "unsubscribe": IntentRouteConfig("HUMAN", "human_service", "退订"),
    "exit": IntentRouteConfig("HUMAN", "human_service", "退出"),
    "cancel": IntentRouteConfig("HUMAN", "human_service", "取消"),
    "delete_account": IntentRouteConfig("HUMAN", "human_service", "删除账号"),
    "product_price": IntentRouteConfig("AGENT", "product_price", "商品价格"),
    "product_stock": IntentRouteConfig("AGENT", "product_stock", "商品库存"),
    "delivery_time": IntentRouteConfig("AGENT", "delivery_time", "发货时效"),
    "order_status": IntentRouteConfig("AGENT", "order_status", "订单状态"),
    "logistics_status": IntentRouteConfig("AGENT", "logistics_status", "物流状态"),
    "invoice": IntentRouteConfig("AGENT", "invoice", "发票"),
    "product_search": IntentRouteConfig("AGENT", "search_products", "商品搜索"),
    "product_inquiry": IntentRouteConfig("AGENT", "search_products", "商品咨询"),
    "unknown_intent": IntentRouteConfig("GENERAL_REPLY", "general_reply", "未知意图"),
    "chitchat": IntentRouteConfig("GENERAL_REPLY", "general_reply", "闲聊"),
    "silent_empty": IntentRouteConfig("SILENT", None, "空消息"),
    "silent_noise": IntentRouteConfig("SILENT", None, "噪音消息"),
}


DEFAULT_RULES: tuple[StrongRuleConfig, ...] = (
    StrongRuleConfig(
        "transfer_request",
        "转人工",
        ("转人工", "人工客服", "真人客服", "找客服"),
        "HUMAN",
        "human_service",
        1.0,
        True,
        "用户明确要求人工介入",
    ),
    StrongRuleConfig(
        "complaint",
        "投诉",
        ("投诉", "举报", "差评", "严重不满", "太差了"),
        "HUMAN",
        "human_service",
        0.98,
        True,
        "投诉类高风险场景",
    ),
    StrongRuleConfig(
        "delete_account",
        "删除账号",
        ("删除账号", "注销账号", "销号", "注销", "删除账户", "把账号删了", "怎么注销", "想注销"),
        "HUMAN",
        "human_service",
        0.98,
        True,
        "账号删除需要人工确认",
    ),
    StrongRuleConfig(
        "unsubscribe",
        "退订",
        ("退订", "别发了", "不要推送"),
        "HUMAN",
        "human_service",
        0.96,
        True,
        "退订类诉求需要人工确认",
    ),
)


DEFAULT_KEYWORD_BOOSTS: tuple[KeywordBoostConfig, ...] = (
    KeywordBoostConfig("订单", "order_status", 0.16, "订单关键词提高订单状态意图"),
    KeywordBoostConfig("物流", "logistics_status", 0.18, "物流关键词提高物流状态意图"),
    KeywordBoostConfig("快递", "logistics_status", 0.18, "快递关键词提高物流状态意图"),
    KeywordBoostConfig("发货", "delivery_time", 0.2, "发货关键词提高发货时效意图"),
    KeywordBoostConfig("今天能发", "delivery_time", 0.24, "明确询问当天发货"),
    KeywordBoostConfig("发票", "invoice", 0.22, "发票关键词提高发票意图"),
    KeywordBoostConfig("多少钱", "product_price", 0.24, "价格关键词提高商品价格意图"),
    KeywordBoostConfig("价格", "product_price", 0.2, "价格关键词提高商品价格意图"),
    KeywordBoostConfig("有货", "product_stock", 0.24, "库存关键词提高商品库存意图"),
    KeywordBoostConfig("库存", "product_stock", 0.2, "库存关键词提高商品库存意图"),
)


DEFAULT_INTENT_CONFIG = IntentRecognitionConfig(
    rules=DEFAULT_RULES,
    keyword_boosts=DEFAULT_KEYWORD_BOOSTS,
    intent_route_map=DEFAULT_INTENT_ROUTE_MAP,
)
