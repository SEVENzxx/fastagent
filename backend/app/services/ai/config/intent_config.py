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
    "abuse": IntentRouteConfig("HUMAN", "human_service", "辱骂攻击"),
    "legal_threat": IntentRouteConfig("HUMAN", "human_service", "法律威胁"),
    "unsubscribe": IntentRouteConfig("HUMAN", "human_service", "退订"),
    "exit": IntentRouteConfig("HUMAN", "human_service", "退出"),
    "cancel": IntentRouteConfig("HUMAN", "human_service", "取消"),
    "delete_account": IntentRouteConfig("HUMAN", "human_service", "删除账号"),
    "return_refund": IntentRouteConfig("HUMAN", "human_service", "退货退款"),
    "product_price": IntentRouteConfig("AGENT", "product_price", "商品价格"),
    "product_stock": IntentRouteConfig("AGENT", "product_stock", "商品库存"),
    "delivery_time": IntentRouteConfig("AGENT", "delivery_time", "发货时效"),
    "order_status": IntentRouteConfig("AGENT", "order_status", "订单状态"),
    "logistics_status": IntentRouteConfig("AGENT", "logistics_status", "物流状态"),
    "invoice": IntentRouteConfig("AGENT", "invoice", "发票"),
    "product_search": IntentRouteConfig("AGENT", "search_products", "商品搜索"),
    "product_inquiry": IntentRouteConfig("AGENT", "search_products", "商品咨询"),
    "return_refund": IntentRouteConfig("HUMAN", "human_service", "退货退款"),
    "unknown_intent": IntentRouteConfig("GENERAL_REPLY", "general_reply", "未知意图"),
    "chitchat": IntentRouteConfig("GENERAL_REPLY", "general_reply", "闲聊"),
    "silent_empty": IntentRouteConfig("SILENT", None, "空消息"),
    "silent_noise": IntentRouteConfig("SILENT", None, "噪音消息"),
    "silent_ack": IntentRouteConfig("SILENT", None, "确认类短句"),
    "silent_thanks": IntentRouteConfig("SILENT", None, "感谢类短句"),
}


DEFAULT_RULES: tuple[StrongRuleConfig, ...] = (
    # ═══════════════════════ HUMAN：必须转人工（按风险降序）══════════════════
    StrongRuleConfig(
        "transfer_request",
        "转人工",
        ("转人工", "人工客服", "真人客服", "找客服", "我要人工", "人工", "给我转人工"),
        "HUMAN",
        "human_service",
        1.0,
        True,
        "用户明确要求人工介入",
    ),
    StrongRuleConfig(
        "abuse",
        "辱骂攻击",
        ("傻逼", "草泥马", "你妈", "操你", "去死", "垃圾东西"),
        "HUMAN",
        "human_service",
        1.0,
        True,
        "辱骂/攻击性言论，需人工安抚",
    ),
    StrongRuleConfig(
        "legal_threat",
        "法律威胁",
        ("起诉", "工商局", "12315", "报警", "律师函", "法院", "消协", "投诉你们公司"),
        "HUMAN",
        "human_service",
        1.0,
        True,
        "法律/监管投诉，风险升级",
    ),
    StrongRuleConfig(
        "complaint",
        "投诉",
        ("投诉", "举报", "差评", "严重不满", "太差了", "太坑了"),
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
        "return_refund",
        "退货退款",
        ("退款", "退货", "我要退", "申请退款", "退钱", "怎么退", "给我退了", "不想要了"),
        "HUMAN",
        "human_service",
        0.96,
        True,
        "退换货诉求需人工处理",
    ),
    StrongRuleConfig(
        "unsubscribe",
        "退订",
        ("退订", "别发了", "不要推送", "别再发了"),
        "HUMAN",
        "human_service",
        0.96,
        True,
        "退订类诉求需要人工确认",
    ),

    # ═══════════════════ SILENT：不需要回复（按频率降序）══════════════════
    StrongRuleConfig(
        "silent_ack",
        "确认类短句",
        ("好的", "知道了", "嗯", "哦", "OK", "ok", "收到", "明白", "行", "好"),
        "SILENT",
        None,
        1.0,
        True,
        "纯确认/收到类短句，无需回复",
    ),
    StrongRuleConfig(
        "silent_thanks",
        "感谢类短句",
        ("谢谢", "多谢", "感谢", "谢谢啦", "3Q", "thx"),
        "SILENT",
        None,
        1.0,
        True,
        "纯感谢类短句，无需回复",
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


def build_intent_config(
    *,
    rules: tuple[StrongRuleConfig, ...] | None = None,
    keyword_boosts: tuple[KeywordBoostConfig, ...] | None = None,
    intent_route_map: dict[str, IntentRouteConfig] | None = None,
    **overrides,
) -> IntentRecognitionConfig:
    """构建意图识别配置，支持租户级覆盖（当前使用默认值，后续从 DB 读取）。

    覆盖规则：传入的参数覆盖默认值，未传入的使用平台默认。
    """
    return IntentRecognitionConfig(
        vector_top_k=overrides.get("vector_top_k", DEFAULT_INTENT_CONFIG.vector_top_k),
        vector_min_score=overrides.get("vector_min_score", DEFAULT_INTENT_CONFIG.vector_min_score),
        high_confidence_score=overrides.get("high_confidence_score", DEFAULT_INTENT_CONFIG.high_confidence_score),
        ambiguous_gap=overrides.get("ambiguous_gap", DEFAULT_INTENT_CONFIG.ambiguous_gap),
        enable_llm_fallback=overrides.get("enable_llm_fallback", DEFAULT_INTENT_CONFIG.enable_llm_fallback),
        enable_multi_intent=overrides.get("enable_multi_intent", DEFAULT_INTENT_CONFIG.enable_multi_intent),
        rules=rules or DEFAULT_RULES,
        keyword_boosts=keyword_boosts or DEFAULT_KEYWORD_BOOSTS,
        intent_route_map=intent_route_map or DEFAULT_INTENT_ROUTE_MAP,
    )
