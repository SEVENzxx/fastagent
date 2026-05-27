"""GENERAL_REPLY 路由处理器。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from app.config import settings
from app.integrations.llm_client import LLMClient, LLMClientError
from app.services.ai.intent.types import RoutedIntent

logger = logging.getLogger(__name__)


async def handle_general_reply(routed: RoutedIntent) -> AsyncIterator[str]:
    """用平台托管的小模型流式生成通用回复。

    GENERAL_REPLY 处理闲聊、跑题、未知意图和澄清类问题。这里优先调用
    `.env` 中配置的小模型，并通过 SSE 流式返回；服务异常时返回固定兜底话术。

    上层通过 ``async for chunk in handle_general_reply(routed):`` 消费，
    每个 chunk 是模型实时输出的片段。
    """
    user_text = _build_user_text(routed)
    logger.info(
        "通用回复开始生成：intent=%s confidence=%.4f clarify=%s user_text_len=%s",
        routed.primary_intent,
        routed.confidence,
        routed.need_clarification,
        len(user_text),
    )
    task_hint = (
        "用户意图不明确，请先礼貌说明你还需要更多信息，并引导用户补充商品、订单、物流或发票等业务细节。"
        if routed.need_clarification
        else "请根据用户内容自然回复，并尽量引导用户补充业务信息。"
    )
    messages = [
        {
            "role": "system",
            "content": f"你是企业微信客服助手。请用简洁、自然、礼貌的中文回复用户。{task_hint}",
        },
        {"role": "user", "content": user_text},
    ]
    try:
        has_output = False
        chunks = 0
        async for chunk in LLMClient().stream(
            messages,
            model=settings.AI_GENERAL_REPLY_MODEL or settings.AI_LLM_MODEL,
            temperature=settings.AI_GENERAL_REPLY_TEMPERATURE,
        ):
            has_output = True
            chunks += 1
            yield chunk
        if not has_output:
            logger.warning("通用回复模型返回空内容，使用兜底回复")
            yield _fallback(routed)
        else:
            logger.info("通用回复生成完成：chunks=%s", chunks)
    except LLMClientError as exc:
        logger.warning("通用回复模型调用失败，使用兜底回复：error=%s", exc)
        yield _fallback(routed)


def _fallback(routed: RoutedIntent) -> str:
    if routed.need_clarification:
        return "我还需要再确认一下你的具体需求，可以补充说明吗？"
    return "我先帮你确认一下，可以再描述具体需求吗？"


def _build_user_text(routed: RoutedIntent) -> str:
    """从路由结果中还原用户文本，供通用回复模型生成上下文相关回复。"""
    segments = [hit.segment for hit in routed.hits if hit.segment]
    return "；".join(segments) or "用户暂未提供明确问题"
