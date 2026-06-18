"""意图识别配置 — 强规则 / 路由映射 / 关键词加权。

从旧 intent/config.py 迁移至此。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.ai.recognition import constants as c
from app.ai.recognition.types import RiskLevel, SkillName


# ══ 配置数据结构 ══


@dataclass(frozen=True, slots=True)
class StrongRuleConfig:
    """强规则 — 关键词命中后直接决定路由，跳过 LLM。

    should_stop=True 时命中即停止流水线，不继续向量 / LLM 步骤。
    """

    intent: str
    label: str
    keywords: tuple[str, ...]
    route: c.RouteType
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

    route: c.RouteType
    skill: str | None = None
    label: str = ""


@dataclass(frozen=True, slots=True)
class IntentRecognitionConfig:
    """意图识别流水线总配置。"""

    vector_top_k: int = 20
    vector_min_score: float = 0.65
    high_confidence_score: float = 0.83
    high_confidence_gap: float = 0.10
    ambiguous_gap: float = 0.05
    enable_llm_fallback: bool = True
    enable_multi_intent: bool = True
    rules: tuple[StrongRuleConfig, ...] = field(default_factory=tuple)
    keyword_boosts: tuple[KeywordBoostConfig, ...] = field(default_factory=tuple)
    intent_route_map: dict[str, IntentRouteConfig] = field(default_factory=dict)

    def route_for(self, intent: str) -> IntentRouteConfig:
        """查 intent → route/skill；未注册兜底为 unknown_intent。"""
        return self.intent_route_map.get(intent, self.intent_route_map[c.INTENT_UNKNOWN])

    def label_for(self, intent: str) -> str:
        """查 intent → 中文标签。"""
        route = self.intent_route_map.get(intent)
        return route.label if route and route.label else intent

    def skill_for(self, intent: str) -> tuple[SkillName, RiskLevel]:
        """查 intent → (SkillName, RiskLevel)；未注册兜底 FALLBACK / READ_ONLY。"""
        route = self.route_for(intent)
        return _resolve_skill_and_risk(route.route, route.skill or "")


# ══ skill ↔ risk 映射工具 ══

_SKILL_RISK_MAP: dict[str, tuple[SkillName, RiskLevel]] = {
    c.SKILL_HUMAN_SERVICE: (SkillName.HUMAN, RiskLevel.HIGH_RISK_WRITE),
    c.SKILL_PRODUCT_PRICE: (SkillName.PRODUCT, RiskLevel.READ_ONLY),
    c.SKILL_PRODUCT_STOCK: (SkillName.PRODUCT, RiskLevel.READ_ONLY),
    c.SKILL_SEARCH_PRODUCTS: (SkillName.PRODUCT, RiskLevel.READ_ONLY),
    c.SKILL_ORDER_STATUS: (SkillName.ORDER, RiskLevel.READ_ONLY),
    c.SKILL_LOGISTICS_STATUS: (SkillName.ORDER, RiskLevel.READ_ONLY),
    c.SKILL_CREATE_ORDER: (SkillName.ORDER, RiskLevel.LOW_RISK_WRITE),
    c.SKILL_CONFIRM_ORDER: (SkillName.ORDER, RiskLevel.HIGH_RISK_WRITE),
    c.SKILL_DELIVERY_TIME: (SkillName.RAG, RiskLevel.READ_ONLY),
    c.SKILL_INVOICE: (SkillName.RAG, RiskLevel.READ_ONLY),
    c.SKILL_DISCOUNT_REQUEST: (SkillName.RAG, RiskLevel.READ_ONLY),
    c.SKILL_REMEMBER_INFO: (SkillName.MEMORY, RiskLevel.LOW_RISK_WRITE),
    c.SKILL_GENERAL_REPLY: (SkillName.RAG, RiskLevel.READ_ONLY),
}

_ROUTE_FALLBACK_MAP: dict[str, tuple[SkillName, RiskLevel]] = {
    c.ROUTE_HUMAN: (SkillName.HUMAN, RiskLevel.HIGH_RISK_WRITE),
    c.ROUTE_AGENT: (SkillName.FALLBACK, RiskLevel.READ_ONLY),
    c.ROUTE_GENERAL_REPLY: (SkillName.RAG, RiskLevel.READ_ONLY),
    c.ROUTE_SILENT: (SkillName.TEMPLATE, RiskLevel.READ_ONLY),
}


def _resolve_skill_and_risk(route: str, skill: str) -> tuple[SkillName, RiskLevel]:
    """按 skill 字符串解析 SkillName + RiskLevel；未注册时按 route 兜底。"""
    if skill and skill in _SKILL_RISK_MAP:
        return _SKILL_RISK_MAP[skill]
    if route in _ROUTE_FALLBACK_MAP:
        return _ROUTE_FALLBACK_MAP[route]
    return SkillName.FALLBACK, RiskLevel.READ_ONLY


# ══ 平台默认配置 ══

# ── intent → (route, skill) 映射 ──
DEFAULT_INTENT_ROUTE_MAP: dict[str, IntentRouteConfig] = {
    # HUMAN
    c.INTENT_TRANSFER_REQUEST: IntentRouteConfig(c.ROUTE_HUMAN, c.SKILL_HUMAN_SERVICE, "转人工"),
    c.INTENT_COMPLAINT: IntentRouteConfig(c.ROUTE_HUMAN, c.SKILL_HUMAN_SERVICE, "投诉"),
    c.INTENT_ABUSE: IntentRouteConfig(c.ROUTE_HUMAN, c.SKILL_HUMAN_SERVICE, "辱骂攻击"),
    c.INTENT_LEGAL_THREAT: IntentRouteConfig(c.ROUTE_HUMAN, c.SKILL_HUMAN_SERVICE, "法律威胁"),
    c.INTENT_UNSUBSCRIBE: IntentRouteConfig(c.ROUTE_HUMAN, c.SKILL_HUMAN_SERVICE, "退订"),
    c.INTENT_EXIT: IntentRouteConfig(c.ROUTE_HUMAN, c.SKILL_HUMAN_SERVICE, "退出"),
    c.INTENT_CANCEL: IntentRouteConfig(c.ROUTE_HUMAN, c.SKILL_HUMAN_SERVICE, "取消"),
    c.INTENT_DELETE_ACCOUNT: IntentRouteConfig(c.ROUTE_HUMAN, c.SKILL_HUMAN_SERVICE, "删除账号"),
    c.INTENT_RETURN_REFUND: IntentRouteConfig(c.ROUTE_HUMAN, c.SKILL_HUMAN_SERVICE, "退货退款"),
    # AGENT
    c.INTENT_PRODUCT_PRICE: IntentRouteConfig(c.ROUTE_AGENT, c.SKILL_PRODUCT_PRICE, "商品价格"),
    c.INTENT_PRODUCT_STOCK: IntentRouteConfig(c.ROUTE_AGENT, c.SKILL_PRODUCT_STOCK, "商品库存"),
    c.INTENT_ORDER_STATUS: IntentRouteConfig(c.ROUTE_AGENT, c.SKILL_ORDER_STATUS, "订单状态"),
    c.INTENT_LOGISTICS_STATUS: IntentRouteConfig(c.ROUTE_AGENT, c.SKILL_LOGISTICS_STATUS, "物流状态"),
    c.INTENT_PRODUCT_SEARCH: IntentRouteConfig(c.ROUTE_AGENT, c.SKILL_SEARCH_PRODUCTS, "商品搜索"),
    c.INTENT_PRODUCT_INQUIRY: IntentRouteConfig(c.ROUTE_AGENT, c.SKILL_SEARCH_PRODUCTS, "商品咨询"),
    c.INTENT_PLACE_ORDER: IntentRouteConfig(c.ROUTE_AGENT, c.SKILL_CREATE_ORDER, "下单"),
    c.INTENT_CONFIRM_ORDER: IntentRouteConfig(c.ROUTE_AGENT, c.SKILL_CONFIRM_ORDER, "确认订单"),
    c.INTENT_SAVE_PREFERENCE: IntentRouteConfig(c.ROUTE_AGENT, c.SKILL_REMEMBER_INFO, "保存偏好"),

    c.INTENT_UNKNOWN: IntentRouteConfig(c.ROUTE_GENERAL_REPLY, c.SKILL_GENERAL_REPLY, "未知意图"),

    # SILENT
    c.INTENT_SILENT_EMPTY: IntentRouteConfig(c.ROUTE_SILENT, None, "空消息"),
    c.INTENT_SILENT_NOISE: IntentRouteConfig(c.ROUTE_SILENT, None, "噪音消息"),
    c.INTENT_SILENT_ACK: IntentRouteConfig(c.ROUTE_SILENT, None, "确认类短句"),
    c.INTENT_SILENT_THANKS: IntentRouteConfig(c.ROUTE_SILENT, None, "感谢类短句"),
}

# ── 强规则 ──
DEFAULT_RULES: tuple[StrongRuleConfig, ...] = (
    StrongRuleConfig(c.INTENT_TRANSFER_REQUEST, "转人工",
        ("转人工", "人工客服", "真人客服", "找客服", "我要人工", "人工", "给我转人工"),
        c.ROUTE_HUMAN, c.SKILL_HUMAN_SERVICE, 1.0, True, "用户明确要求人工介入"),
    StrongRuleConfig(c.INTENT_ABUSE, "辱骂攻击",
        ("傻逼", "草泥马", "你妈", "操你", "去死", "垃圾东西"),
        c.ROUTE_HUMAN, c.SKILL_HUMAN_SERVICE, 1.0, True, "辱骂/攻击性言论"),
    StrongRuleConfig(c.INTENT_LEGAL_THREAT, "法律威胁",
        ("起诉", "工商局", "12315", "报警", "律师函", "法院", "消协", "投诉你们公司"),
        c.ROUTE_HUMAN, c.SKILL_HUMAN_SERVICE, 1.0, True, "法律/监管投诉"),
    StrongRuleConfig(c.INTENT_COMPLAINT, "投诉",
        ("投诉", "举报", "差评", "严重不满", "太差了", "太坑了"),
        c.ROUTE_HUMAN, c.SKILL_HUMAN_SERVICE, 0.98, True, "投诉类高风险场景"),
    StrongRuleConfig(c.INTENT_DELETE_ACCOUNT, "删除账号",
        ("删除账号", "注销账号", "销号", "注销", "删除账户", "把账号删了", "怎么注销", "想注销"),
        c.ROUTE_HUMAN, c.SKILL_HUMAN_SERVICE, 0.98, True, "账号删除需人工确认"),
    StrongRuleConfig(c.INTENT_RETURN_REFUND, "退货退款",
        ("退款", "退货", "我要退", "申请退款", "退钱", "怎么退", "给我退了", "不想要了"),
        c.ROUTE_HUMAN, c.SKILL_HUMAN_SERVICE, 0.96, True, "退换货需人工处理"),
    StrongRuleConfig(c.INTENT_UNSUBSCRIBE, "退订",
        ("退订", "别发了", "不要推送", "别再发了"),
        c.ROUTE_HUMAN, c.SKILL_HUMAN_SERVICE, 0.96, True, "退订需人工确认"),
    StrongRuleConfig(c.INTENT_SILENT_ACK, "确认类短句",
        ("好的", "知道了", "嗯", "哦", "OK", "ok", "收到", "明白", "行", "好"),
        c.ROUTE_SILENT, None, 1.0, True, "纯确认/收到"),
    StrongRuleConfig(c.INTENT_SILENT_THANKS, "感谢类短句",
        ("谢谢", "多谢", "感谢", "谢谢啦", "3Q", "thx"),
        c.ROUTE_SILENT, None, 1.0, True, "纯感谢"),
)

# ── 关键词加权 ──
DEFAULT_KEYWORD_BOOSTS: tuple[KeywordBoostConfig, ...] = (
    KeywordBoostConfig("订单", c.INTENT_ORDER_STATUS, 0.16),
    KeywordBoostConfig("物流", c.INTENT_LOGISTICS_STATUS, 0.18),
    KeywordBoostConfig("快递", c.INTENT_LOGISTICS_STATUS, 0.18),
    KeywordBoostConfig("发货", c.INTENT_DELIVERY_TIME, 0.20),
    KeywordBoostConfig("今天能发", c.INTENT_DELIVERY_TIME, 0.24),
    KeywordBoostConfig("发票", c.INTENT_INVOICE, 0.22),
    KeywordBoostConfig("多少钱", c.INTENT_PRODUCT_PRICE, 0.24),
    KeywordBoostConfig("价格", c.INTENT_PRODUCT_PRICE, 0.20),
    KeywordBoostConfig("有货", c.INTENT_PRODUCT_STOCK, 0.24),
    KeywordBoostConfig("库存", c.INTENT_PRODUCT_STOCK, 0.20),
    KeywordBoostConfig("下单", c.INTENT_PLACE_ORDER, 0.26),
    KeywordBoostConfig("帮我订", c.INTENT_PLACE_ORDER, 0.24),
    KeywordBoostConfig("买一个", c.INTENT_PLACE_ORDER, 0.22),
    KeywordBoostConfig("确认订单", c.INTENT_CONFIRM_ORDER, 0.28),
    KeywordBoostConfig("就这个了", c.INTENT_CONFIRM_ORDER, 0.24),
    KeywordBoostConfig("便宜", c.INTENT_DISCOUNT_REQUEST, 0.22),
    KeywordBoostConfig("打折", c.INTENT_DISCOUNT_REQUEST, 0.22),
    KeywordBoostConfig("记住", c.INTENT_SAVE_PREFERENCE, 0.26),
    KeywordBoostConfig("备注", c.INTENT_SAVE_PREFERENCE, 0.22),
)

# ── 聚合为平台默认配置 ──
DEFAULT_INTENT_CONFIG = IntentRecognitionConfig(
    rules=DEFAULT_RULES,
    keyword_boosts=DEFAULT_KEYWORD_BOOSTS,
    intent_route_map=DEFAULT_INTENT_ROUTE_MAP,
)
