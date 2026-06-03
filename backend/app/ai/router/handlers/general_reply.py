"""GENERAL_REPLY 路由处理器 — 无意图命中时的通用回复，RAG 增强。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from app.config import settings
from app.ai.router.handlers.registry import register_handler
from app.ai.classifier.types import ROUTE_GENERAL_REPLY, RoutedIntent
from app.ai.llm.gateway import LLMClientError, LLMUseCase, stream
from app.ai.llm.prompts.general_reply import (
    build_clarify_messages,
    build_general_reply_messages,
    build_rag_reply_messages,
)
from app.ai.types import Messages
from app.ai.rag.vector_search import VectorDomain, VectorSearchService

if TYPE_CHECKING:
    from app.ai.agent.types import AgentContext

logger = logging.getLogger(__name__)

_FALLBACK_TEXT = "我先帮你确认一下，可以再描述具体需求吗？"


async def _stream(
    use_case: LLMUseCase,
    messages: Messages,
    *,
    tenant_id: int | None = None,
) -> AsyncIterator[str]:
    """按用途选择模型并流式调用 LLM。"""
    try:
        has_output = False
        async for chunk in stream(use_case, messages, tenant_id=tenant_id, temperature=0.2):
            has_output = True
            yield chunk
        if not has_output:
            yield _FALLBACK_TEXT
    except LLMClientError as exc:
        logger.warning("通用回复 LLM 失败: %s", exc)
        yield _FALLBACK_TEXT


async def _retrieve_knowledge(query: str, tenant_id: int) -> str:
    """从 Qdrant 知识库检索并拼接上下文。"""
    try:
        vs = VectorSearchService()
        hits = await vs.search_text(
            domain=VectorDomain.KNOWLEDGE_CHUNK, tenant_id=tenant_id, query=query,
            top_k=settings.AI_GENERAL_REPLY_RAG_TOP_K,
            min_score=settings.AI_GENERAL_REPLY_RAG_MIN_SCORE,
        )
    except Exception:
        return ""
    return "\n".join(f"- {h.payload.get('text', '')}" for h in hits) if hits else ""


def _build_user_text(routed: RoutedIntent) -> str:
    segments = [h.segment for h in routed.hits if h.segment]
    return "；".join(segments) or "用户暂未提供明确问题"


@register_handler(ROUTE_GENERAL_REPLY)
class GeneralReplyHandler:
    route = ROUTE_GENERAL_REPLY
    reply_sender_type = "AI"
    clear_pending_state = False
    transfer_to_human = False
    send_ai_greeting = True
    show_typing = True
    requires_agent_context = False
    tool_results: list[dict] = []

    async def stream(
        self, routed: RoutedIntent, *, agent_context: AgentContext | None = None,
    ) -> AsyncIterator[str]:
        """通用回复：RAG 命中 → 租户模型；否则 → 本地 AI_LLM_MODEL。"""
        user_text = _build_user_text(routed)
        tenant_id = agent_context.tenant_id if agent_context else None

        # 意图不明确 → 本地模型直接澄清
        if routed.need_clarification:
            async for chunk in _stream(LLMUseCase.GENERAL_REPLY, build_clarify_messages(user_text)):
                yield chunk
            return

        # 检索知识库
        knowledge_context = await _retrieve_knowledge(user_text, tenant_id) if tenant_id else ""

        if knowledge_context:
            # RAG 命中 → 租户模型
            messages = build_rag_reply_messages(user_text, knowledge_context)
            async for chunk in _stream(LLMUseCase.RAG_REPLY, messages, tenant_id=tenant_id):
                yield chunk
        else:
            # 无 RAG → 本地模型兜底
            async for chunk in _stream(LLMUseCase.GENERAL_REPLY, build_general_reply_messages(user_text)):
                yield chunk
