"""SILENT 路由处理器。"""

from __future__ import annotations

from app.services.ai.intent.types import RoutedIntent


async def handle_silent(_routed: RoutedIntent) -> str:
    """静默处理：不回复内容。"""
    return ""
