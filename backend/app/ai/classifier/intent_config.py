"""意图识别配置 — 强规则 / 路由映射 / 关键词加权。

当前先使用代码内配置，后续可以替换为 YAML/DB/管理后台。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.ai.classifier import types as it


# ══ 配置数据结构 ══


@dataclass(frozen=True, slots=True)
class StrongRuleConfig:
    """强规则 — 关键词命中后直接决定路由，跳过 LLM。

    should_stop=True 时命中即停止流水线，不继续向量 / LLM 步骤。
    """

    intent: str
    label: str
    keywords: tuple[str, ...]
    route: it.RouteType
    skill: str | None = None
    confidence: float = 1.0
    should_stop: bool = True
    reason: str = ""


@dataclass(frozen=True, slots=True)
class KeywordBoostConfig:
    """关键词加权 — 命中后给对应 intent 加分，不直接决定路由。"""

    keyword: str
    intent: str
    boost: float
    reason: str = ""


@dataclass(frozen=True, slots=True)
class IntentRouteConfig:
    """intent → (route, skill, label) 映射。"""

    route: it.RouteType
    skill: str | None = None
    label: str = ""


@dataclass(frozen=True, slots=True)
class IntentRecognitionConfig:
    """意图识别流水线总配置。"""

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
        """查 intent → route/skill；未注册兜底为 unknown_intent。"""
        return self.intent_route_map.get(intent, self.intent_route_map[it.INTENT_UNKNOWN])

    def label_for(self, intent: str) -> str:
        """查 intent → 中文标签。"""
        route = self.intent_route_map.get(intent)
        return route.label if route and route.label else intent


# ══ 平台默认配置 ══

# ── intent → (route, skill) 映射 ──
DEFAULT_INTENT_ROUTE_MAP: dict[str, IntentRouteConfig] = {
    # HUMAN（9 个）
    it.INTENT_TRANSFER_REQUEST: IntentRouteConfig(it.ROUTE_HUMAN, it.SKILL_HUMAN_SERVICE, "转人工"),
    it.INTENT_COMPLAINT: IntentRouteConfig(it.ROUTE_HUMAN, it.SKILL_HUMAN_SERVICE, "投诉"),
    it.INTENT_ABUSE: IntentRouteConfig(it.ROUTE_HUMAN, it.SKILL_HUMAN_SERVICE, "辱骂攻击"),
    it.INTENT_LEGAL_THREAT: IntentRouteConfig(it.ROUTE_HUMAN, it.SKILL_HUMAN_SERVICE, "法律威胁"),
    it.INTENT_UNSUBSCRIBE: IntentRouteConfig(it.ROUTE_HUMAN, it.SKILL_HUMAN_SERVICE, "退订"),
    it.INTENT_EXIT: IntentRouteConfig(it.ROUTE_HUMAN, it.SKILL_HUMAN_SERVICE, "退出"),
    it.INTENT_CANCEL: IntentRouteConfig(it.ROUTE_HUMAN, it.SKILL_HUMAN_SERVICE, "取消"),
    it.INTENT_DELETE_ACCOUNT: IntentRouteConfig(it.ROUTE_HUMAN, it.SKILL_HUMAN_SERVICE, "删除账号"),
    it.INTENT_RETURN_REFUND: IntentRouteConfig(it.ROUTE_HUMAN, it.SKILL_HUMAN_SERVICE, "退货退款"),
    # AGENT（12 个）
    it.INTENT_PRODUCT_PRICE: IntentRouteConfig(it.ROUTE_AGENT, it.SKILL_PRODUCT_PRICE, "商品价格"),
    it.INTENT_PRODUCT_STOCK: IntentRouteConfig(it.ROUTE_AGENT, it.SKILL_PRODUCT_STOCK, "商品库存"),
    it.INTENT_DELIVERY_TIME: IntentRouteConfig(it.ROUTE_AGENT, it.SKILL_DELIVERY_TIME, "发货时效"),
    it.INTENT_ORDER_STATUS: IntentRouteConfig(it.ROUTE_AGENT, it.SKILL_ORDER_STATUS, "订单状态"),
    it.INTENT_LOGISTICS_STATUS: IntentRouteConfig(it.ROUTE_AGENT, it.SKILL_LOGISTICS_STATUS, "物流状态"),
    it.INTENT_INVOICE: IntentRouteConfig(it.ROUTE_AGENT, it.SKILL_INVOICE, "发票"),
    it.INTENT_PRODUCT_SEARCH: IntentRouteConfig(it.ROUTE_AGENT, it.SKILL_SEARCH_PRODUCTS, "商品搜索"),
    it.INTENT_PRODUCT_INQUIRY: IntentRouteConfig(it.ROUTE_AGENT, it.SKILL_SEARCH_PRODUCTS, "商品咨询"),
    it.INTENT_PLACE_ORDER: IntentRouteConfig(it.ROUTE_AGENT, it.SKILL_CREATE_ORDER, "下单"),
    it.INTENT_CONFIRM_ORDER: IntentRouteConfig(it.ROUTE_AGENT, it.SKILL_CONFIRM_ORDER, "确认订单"),
    it.INTENT_DISCOUNT_REQUEST: IntentRouteConfig(it.ROUTE_AGENT, it.SKILL_DISCOUNT_REQUEST, "议价"),
    it.INTENT_SAVE_PREFERENCE: IntentRouteConfig(it.ROUTE_AGENT, it.SKILL_REMEMBER_INFO, "保存偏好"),
    # GENERAL_REPLY（2 个）
    it.INTENT_UNKNOWN: IntentRouteConfig(it.ROUTE_GENERAL_REPLY, it.SKILL_GENERAL_REPLY, "未知意图"),
    it.INTENT_CHITCHAT: IntentRouteConfig(it.ROUTE_GENERAL_REPLY, it.SKILL_GENERAL_REPLY, "闲聊"),
    # SILENT（4 个）
    it.INTENT_SILENT_EMPTY: IntentRouteConfig(it.ROUTE_SILENT, None, "空消息"),
    it.INTENT_SILENT_NOISE: IntentRouteConfig(it.ROUTE_SILENT, None, "噪音消息"),
    it.INTENT_SILENT_ACK: IntentRouteConfig(it.ROUTE_SILENT, None, "确认类短句"),
    it.INTENT_SILENT_THANKS: IntentRouteConfig(it.ROUTE_SILENT, None, "感谢类短句"),
}

# ── 强规则 — 按风险降序，命中即停止 ──
DEFAULT_RULES: tuple[StrongRuleConfig, ...] = (
    # ══ HUMAN（7 个）══
    StrongRuleConfig(it.INTENT_TRANSFER_REQUEST, "转人工",
        ("转人工", "人工客服", "真人客服", "找客服", "我要人工", "人工", "给我转人工"),
        it.ROUTE_HUMAN, it.SKILL_HUMAN_SERVICE, 1.0, True, "用户明确要求人工介入"),
    StrongRuleConfig(it.INTENT_ABUSE, "辱骂攻击",
        ("傻逼", "草泥马", "你妈", "操你", "去死", "垃圾东西"),
        it.ROUTE_HUMAN, it.SKILL_HUMAN_SERVICE, 1.0, True, "辱骂/攻击性言论"),
    StrongRuleConfig(it.INTENT_LEGAL_THREAT, "法律威胁",
        ("起诉", "工商局", "12315", "报警", "律师函", "法院", "消协", "投诉你们公司"),
        it.ROUTE_HUMAN, it.SKILL_HUMAN_SERVICE, 1.0, True, "法律/监管投诉"),
    StrongRuleConfig(it.INTENT_COMPLAINT, "投诉",
        ("投诉", "举报", "差评", "严重不满", "太差了", "太坑了"),
        it.ROUTE_HUMAN, it.SKILL_HUMAN_SERVICE, 0.98, True, "投诉类高风险场景"),
    StrongRuleConfig(it.INTENT_DELETE_ACCOUNT, "删除账号",
        ("删除账号", "注销账号", "销号", "注销", "删除账户", "把账号删了", "怎么注销", "想注销"),
        it.ROUTE_HUMAN, it.SKILL_HUMAN_SERVICE, 0.98, True, "账号删除需人工确认"),
    StrongRuleConfig(it.INTENT_RETURN_REFUND, "退货退款",
        ("退款", "退货", "我要退", "申请退款", "退钱", "怎么退", "给我退了", "不想要了"),
        it.ROUTE_HUMAN, it.SKILL_HUMAN_SERVICE, 0.96, True, "退换货需人工处理"),
    StrongRuleConfig(it.INTENT_UNSUBSCRIBE, "退订",
        ("退订", "别发了", "不要推送", "别再发了"),
        it.ROUTE_HUMAN, it.SKILL_HUMAN_SERVICE, 0.96, True, "退订需人工确认"),

    # ══ SILENT（2 个）══
    StrongRuleConfig(it.INTENT_SILENT_ACK, "确认类短句",
        ("好的", "知道了", "嗯", "哦", "OK", "ok", "收到", "明白", "行", "好"),
        it.ROUTE_SILENT, None, 1.0, True, "纯确认/收到"),
    StrongRuleConfig(it.INTENT_SILENT_THANKS, "感谢类短句",
        ("谢谢", "多谢", "感谢", "谢谢啦", "3Q", "thx"),
        it.ROUTE_SILENT, None, 1.0, True, "纯感谢"),
)

# ── 关键词加权 — 命中后给 intent 加分，配合向量召回使用 ──
DEFAULT_KEYWORD_BOOSTS: tuple[KeywordBoostConfig, ...] = (
    KeywordBoostConfig("订单", it.INTENT_ORDER_STATUS, 0.16),
    KeywordBoostConfig("物流", it.INTENT_LOGISTICS_STATUS, 0.18),
    KeywordBoostConfig("快递", it.INTENT_LOGISTICS_STATUS, 0.18),
    KeywordBoostConfig("发货", it.INTENT_DELIVERY_TIME, 0.20),
    KeywordBoostConfig("今天能发", it.INTENT_DELIVERY_TIME, 0.24),
    KeywordBoostConfig("发票", it.INTENT_INVOICE, 0.22),
    KeywordBoostConfig("多少钱", it.INTENT_PRODUCT_PRICE, 0.24),
    KeywordBoostConfig("价格", it.INTENT_PRODUCT_PRICE, 0.20),
    KeywordBoostConfig("有货", it.INTENT_PRODUCT_STOCK, 0.24),
    KeywordBoostConfig("库存", it.INTENT_PRODUCT_STOCK, 0.20),
    KeywordBoostConfig("下单", it.INTENT_PLACE_ORDER, 0.26),
    KeywordBoostConfig("帮我订", it.INTENT_PLACE_ORDER, 0.24),
    KeywordBoostConfig("买一个", it.INTENT_PLACE_ORDER, 0.22),
    KeywordBoostConfig("确认订单", it.INTENT_CONFIRM_ORDER, 0.28),
    KeywordBoostConfig("就这个了", it.INTENT_CONFIRM_ORDER, 0.24),
    KeywordBoostConfig("便宜", it.INTENT_DISCOUNT_REQUEST, 0.22),
    KeywordBoostConfig("打折", it.INTENT_DISCOUNT_REQUEST, 0.22),
    KeywordBoostConfig("优惠", it.INTENT_DISCOUNT_REQUEST, 0.20),
    KeywordBoostConfig("记住", it.INTENT_SAVE_PREFERENCE, 0.26),
    KeywordBoostConfig("备注", it.INTENT_SAVE_PREFERENCE, 0.22),
)

# ── 聚合为平台默认配置 ──
DEFAULT_INTENT_CONFIG = IntentRecognitionConfig(
    rules=DEFAULT_RULES,
    keyword_boosts=DEFAULT_KEYWORD_BOOSTS,
    intent_route_map=DEFAULT_INTENT_ROUTE_MAP,
)


