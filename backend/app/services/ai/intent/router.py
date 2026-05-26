"""IntentRouter：最终路由映射。"""

from __future__ import annotations

from app.services.ai.config.intent_config import DEFAULT_INTENT_CONFIG, IntentRecognitionConfig
from app.services.ai.intent.types import IntentResult, RoutedIntent


class IntentRouter:
    """根据最终 intent 映射 RouteType 和 skill。"""

    def __init__(self, config: IntentRecognitionConfig | None = None) -> None:
        self.config = config or DEFAULT_INTENT_CONFIG

    def route(self, result: IntentResult) -> RoutedIntent:
        """将 IntentResult 转换为 RoutedIntent。"""
        primary = result.primary_intent or "unknown_intent"
        route_rule = self.config.route_for(primary)
        return RoutedIntent(
            primary_intent=primary,
            confidence=result.confidence,
            route=route_rule.route,
            skill=route_rule.skill,
            hits=result.hits,
            is_multi_intent=result.is_multi_intent,
            need_clarification=result.need_clarification,
            reason=result.reason,
        )
