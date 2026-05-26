"""HUMAN 路由处理器。"""

from __future__ import annotations

from app.services.ai.intent.types import RoutedIntent


async def handle_human(routed: RoutedIntent) -> str:
    """人工处理占位：后续接人工队列和 WebSocket 通知。"""
    return f"已转人工处理: {routed.primary_intent or 'unknown'}"
