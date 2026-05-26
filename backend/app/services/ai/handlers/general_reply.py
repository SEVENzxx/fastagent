"""GENERAL_REPLY 路由处理器。"""

from __future__ import annotations

from app.config import settings
from app.integrations.llm_client import LLMClient, LLMClientError
from app.services.ai.intent.types import RoutedIntent


async def handle_general_reply(routed: RoutedIntent) -> str:
    """用平台托管的小模型生成通用回复。

    GENERAL_REPLY 处理闲聊、跑题、未知意图和澄清类问题。这里优先调用
    `.env` 中配置的大厂小模型；服务异常时返回固定兜底话术，保证会话链路不中断。
    """
    if routed.need_clarification:
        return "我还需要再确认一下你的具体需求，可以补充说明吗？"

    user_text = _build_user_text(routed)
    messages = [
        {
            "role": "system",
            "content": "你是企业微信客服助手。请用简洁、自然、礼貌的中文回复用户，并引导用户补充业务信息。",
        },
        {"role": "user", "content": user_text},
    ]
    try:
        reply = await LLMClient().chat(
            messages,
            model=settings.AI_GENERAL_REPLY_MODEL or settings.AI_LLM_MODEL,
            max_new_tokens=settings.AI_GENERAL_REPLY_MAX_TOKENS,
            temperature=settings.AI_GENERAL_REPLY_TEMPERATURE,
        )
    except LLMClientError:
        return "我先帮你确认一下，可以再描述具体需求吗？"

    return reply or "我先帮你确认一下，可以再描述具体需求吗？"


def _build_user_text(routed: RoutedIntent) -> str:
    """从路由结果中还原用户文本，供通用回复模型生成上下文相关回复。"""
    segments = [hit.segment for hit in routed.hits if hit.segment]
    return "；".join(segments) or "用户暂未提供明确问题"
