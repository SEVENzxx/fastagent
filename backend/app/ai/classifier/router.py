"""IntentRouter：最终路由映射。"""

from __future__ import annotations

from app.ai.classifier.intent_config import DEFAULT_INTENT_CONFIG, IntentRecognitionConfig
from app.ai.classifier.types import IntentResult, RoutedIntent


class IntentRouter:
    """根据最终 intent 映射 RouteType 和 skill。

    ── 处理步骤 ──
      1. 取 primary_intent，若为空兜底为 unknown_intent
      2. 查 intent_route_map → 得到 route（SILENT/GENERAL_REPLY/AGENT/HUMAN）+ skill
      3. 从 IntentResult 中提取 hits / is_multi_intent / need_clarification / reason
      4. 组装 RoutedIntent 返回（给 MessageRouter 分发用）
    """

    def __init__(self, config: IntentRecognitionConfig | None = None) -> None:
        self.config = config or DEFAULT_INTENT_CONFIG

    def route(self, result: IntentResult) -> RoutedIntent:
        """将 IntentResult 转换为 RoutedIntent。"""
        # ── 1: 取 primary_intent ──
        primary = result.primary_intent or "unknown_intent"

        # ── 2: 查路由映射 → route + skill ──
        route_rule = self.config.route_for(primary)

        # ── 3-4: 组装 RoutedIntent（含 hits / 多意图 / 澄清标记）──
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
