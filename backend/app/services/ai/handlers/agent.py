"""AGENT 路由处理器。"""

from __future__ import annotations

from app.services.ai.intent.types import RoutedIntent


async def handle_agent(routed: RoutedIntent) -> str:
    """业务技能占位：Phase 9 接 LangGraph/Skill Registry。"""
    return f"调用业务能力: {routed.skill or routed.primary_intent or 'unknown'}"
