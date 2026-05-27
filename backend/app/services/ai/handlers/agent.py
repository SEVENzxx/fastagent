"""AGENT 路由处理器。"""

from __future__ import annotations

import logging

from app.services.ai.intent.types import RoutedIntent

logger = logging.getLogger(__name__)


async def handle_agent(routed: RoutedIntent) -> str:
    """业务技能占位：Phase 9 接 LangGraph/Skill Registry。"""
    logger.info(
        "AGENT 处理器 stub 被调用：intent=%s skill=%s confidence=%.4f hits=%s",
        routed.primary_intent,
        routed.skill,
        routed.confidence,
        len(routed.hits),
    )
    return f"调用业务能力: {routed.skill or routed.primary_intent or 'unknown'}"
