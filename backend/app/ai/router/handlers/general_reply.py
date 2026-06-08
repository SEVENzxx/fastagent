"""GENERAL_REPLY 路由处理器 — 无意图命中时的通用回复，RAG 增强。"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from app.config import settings
from app.ai.agent.reply_templates import fixed_policy_reply
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
from app.services.rag_service import RAGService

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


def _split_query(query: str) -> list[str]:
    """将多意图查询按中文/英文分句符分割，返回非空子句列表。

    例："能开发票不？你们有门店吗" → ["能开发票不", "你们有门店吗"]
    """
    raw = re.split(r"[；;。！？!?\n]+", query)
    return [s.strip() for s in raw if s.strip()] or [query]


async def _retrieve_qa_all(query: str, tenant_id: int) -> list[dict]:
    """从 Qdrant 标准问答对检索全部命中答案，支持一句多问。"""
    sub_queries = _split_query(query)
    seen: set[str] = set()
    items: list[dict] = []

    for sub in sub_queries:
        try:
            matches = await RAGService().search_qa(sub, tenant_id)
        except Exception:
            logger.warning("QA 检索异常: query=%s tenant=%s", sub[:40], tenant_id)
            continue
        if not matches:
            logger.info("QA 未命中: query=%s", sub[:40])
            continue
        logger.info("QA 命中: query=%s matches=%s", sub[:40], len(matches))
        for m in matches:
            answer = str(m.get("answer") or "").strip()
            question = str(m.get("question") or "").strip()
            if answer and answer not in seen:
                seen.add(answer)
                items.append({"question": question, "answer": answer})

    return items


def _render_qa_answers(items: list[dict]) -> str:
    """QA 命中后直接渲染标准答案，不再交给 LLM 改写。"""
    if not items:
        return ""
    if len(items) == 1:
        return str(items[0].get("answer") or "").strip()

    parts: list[str] = []
    for index, item in enumerate(items, start=1):
        answer = str(item.get("answer") or "").strip()
        if not answer:
            continue
        question = str(item.get("question") or "").strip()
        prefix = f"{index}. 关于{question}：" if question else f"{index}. "
        parts.append(f"{prefix}\n{answer}")
    return "\n\n".join(parts)


async def _retrieve_knowledge(query: str, tenant_id: int) -> str:
    """从 Qdrant 知识库检索并拼接上下文。

    支持多意图场景：按分句符分割后分别检索，合并所有不重复的命中片段。
    """
    sub_queries = _split_query(query)
    seen: set[str] = set()
    parts: list[str] = []
    vs = VectorSearchService()

    for sub in sub_queries:
        try:
            hits = await vs.search_text(
                domain=VectorDomain.KNOWLEDGE_CHUNK, tenant_id=tenant_id, query=sub,
                top_k=settings.AI_GENERAL_REPLY_RAG_TOP_K,
                min_score=settings.AI_GENERAL_REPLY_RAG_MIN_SCORE,
            )
        except Exception:
            logger.warning("知识库检索异常: query=%s tenant=%s", sub[:40], tenant_id)
            continue
        if not hits:
            logger.info("知识库未命中: query=%s", sub[:40])
            continue
        logger.info("知识库命中: query=%s hits=%s", sub[:40], len(hits))
        for h in hits:
            text = str(h.payload.get('text', '')).strip()
            if text and text not in seen:
                seen.add(text)
                parts.append(f"- {text}")

    return "\n".join(parts)


def _build_user_text(routed: RoutedIntent) -> str:
    segments = [h.segment for h in routed.hits if h.segment]
    return "；".join(segments) or "用户暂未提供明确问题"


@register_handler(ROUTE_GENERAL_REPLY)
class GeneralReplyHandler:
    route = ROUTE_GENERAL_REPLY
    reply_sender_type = "AI"
    clear_pending_state = True
    transfer_to_human = False
    send_ai_greeting = True
    show_typing = True
    requires_agent_context = False
    tool_results: list[dict] = []

    async def stream(
        self, routed: RoutedIntent, *, agent_context: AgentContext | None = None,
    ) -> AsyncIterator[str]:
        """通用回复：QA 标准答案直出；知识库命中时再由 LLM 合成；无命中走兜底。"""
        user_text = _build_user_text(routed)
        tenant_id = agent_context.tenant_id if agent_context else None

        # ── 路径 1：意图不明确 → 本地模型直接澄清 ──
        if routed.need_clarification:
            logger.info("GENERAL_REPLY 路径: 澄清追问, query=%s", user_text[:40])
            async for chunk in _stream(LLMUseCase.GENERAL_REPLY, build_clarify_messages(user_text)):
                yield chunk
            return

        # ── 路径 2：QA 标准答案命中 → 直接返回，不经过 LLM ──
        qa_items = await _retrieve_qa_all(user_text, tenant_id) if tenant_id else []
        qa_reply = _render_qa_answers(qa_items)
        if qa_reply:
            logger.info("GENERAL_REPLY 路径: QA 直接命中, query=%s qa_count=%s", user_text[:40], len(qa_items))
            yield qa_reply
            return

        fixed_reply = fixed_policy_reply(routed.primary_intent)
        if fixed_reply:
            logger.info("GENERAL_REPLY 路径: 固定政策模板, intent=%s", routed.primary_intent)
            yield fixed_reply
            return

        # ── 路径 3：知识库命中 → LLM 基于知识库合成 ──
        knowledge_context = await _retrieve_knowledge(user_text, tenant_id) if tenant_id else ""
        if knowledge_context:
            logger.info("GENERAL_REPLY 路径: 知识库命中→租户模型合成, query=%s", user_text[:40])
            messages = build_rag_reply_messages(user_text, knowledge_context)
            async for chunk in _stream(LLMUseCase.RAG_REPLY, messages, tenant_id=tenant_id):
                yield chunk
        else:
            # ── 路径 4：无命中 → 本地模型兜底 ──
            logger.info("GENERAL_REPLY 路径: 无命中→本地模型兜底, query=%s", user_text[:40])
            async for chunk in _stream(LLMUseCase.GENERAL_REPLY, build_general_reply_messages(user_text)):
                yield chunk
