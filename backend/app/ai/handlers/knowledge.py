"""KnowledgeHandler — 知识场景 Handler。

支持以下 scenario：
  - knowledge.policy
  - knowledge.qa
  - knowledge.product_qa

Handler 编排 KnowledgeSkill → KnowledgeReplyBuilder。
4 条路径：追问精准续查 → QA 直出 → 知识库检索（短直出/长摘要）→ "未查到"。
不编造知识，无 LLM 兜底。
"""

from __future__ import annotations

import logging
from typing import Any

from app.common.constants.business import KNOWLEDGE_DEIXIS_KEYWORDS, KNOWLEDGE_SHORT_CONTENT_TOKEN_LIMIT
from app.ai.context.pending_state import PendingDirective
from app.ai.handlers.base import BaseHandler, HandlerResult
from app.ai.llm.gateway import LLMUseCase, complete
from app.ai.prompts.knowledge_summary import build_knowledge_summary_messages
from app.ai.recognition.types import ScenarioDecision
from app.ai.reply_builders.knowledge import KnowledgeReplyBuilder
from app.ai.context.session_context import SessionContext
from app.ai.handlers.base import ToolResult
from app.ai.skills.gateway import SkillError, call_skill

logger = logging.getLogger(__name__)


class KnowledgeHandler(BaseHandler):
    """知识问答 Handler。

    依赖 KnowledgeSkill（search_qa / search_knowledge）做知识检索，
    依赖 KnowledgeReplyBuilder 做回复渲染。
    """

    def __init__(self, skill: object = None) -> None:
        self._skill = skill

    async def execute(
        self,
        decision: ScenarioDecision,
        context: object,
    ) -> HandlerResult:
        """处理知识场景。"""
        ctx: SessionContext = context  # type: ignore[assignment]
        scenario = decision.scenario_id
        text = decision.entities.get("raw_text", "")
        if not text:
            text = getattr(ctx, "last_user_message", "") or ""

        self._init_trace_context(scenario)

        if not text.strip():
            result = HandlerResult(
                scenario_id=scenario,
                reply="请描述您想了解的问题。",
                pending_directive=PendingDirective.CLEAR,
            )
        elif scenario == "knowledge.product_qa":
            result = await self._handle_product_qa(text, ctx)
        else:
            result = await self._execute_knowledge(text, ctx, scenario)

        self._merge_trace_context(result)
        return result

    async def _execute_knowledge(
        self,
        text: str,
        ctx: SessionContext,
        scenario: str,
    ) -> HandlerResult:
        """执行知识检索（追问 → QA → 知识库 → 无命中）。"""
        # ── 路径 1：追问续查（针对上次知识引用的精准检索） ──
        if self._is_follow_up(text) and ctx.last_knowledge_refs:
            result = await self._try_follow_up(text, ctx, scenario)
            if result is not None:
                return result

        # ── 路径 2：QA pair 高置信直出 ──
        qa_result = await self._call_skill("search_qa", tenant_id=ctx.tenant_id, query=text)
        if qa_result.ok:
            items = (qa_result.result or {}).get("items", [])
            if items:
                return HandlerResult(
                    scenario_id=scenario,
                    reply=KnowledgeReplyBuilder.qa_direct(items),
                    pending_directive=PendingDirective.CLEAR,
                    context_update={
                        "last_knowledge_topic": text[:80],
                        "last_knowledge_scope": "qa",
                        "last_knowledge_refs": _build_knowledge_refs(items, "qa"),
                    },
                )

        # ── 路径 3：知识分块检索 ──
        kn_result = await self._call_skill(
            "search_knowledge", tenant_id=ctx.tenant_id, query=text,
        )
        if kn_result.ok:
            items = (kn_result.result or {}).get("items", [])
            if items:
                return await self._handle_knowledge_hits(text, items, scenario, ctx.tenant_id)

        # ── 路径 4：无命中 ──
        return HandlerResult(
            scenario_id=scenario,
            reply=KnowledgeReplyBuilder.no_knowledge(),
            pending_directive=PendingDirective.CLEAR,
        )

    async def resume(
        self,
        pending: object,
        message: str,
        context: object,
    ) -> HandlerResult:
        """知识场景不支持 Pending 恢复。"""
        return HandlerResult(
            scenario_id=getattr(pending, "scenario_id", "knowledge.qa"),
            reply=KnowledgeReplyBuilder.no_knowledge(),
            pending_directive=PendingDirective.CLEAR,
        )

    # ── 内部路径 ──

    async def _handle_product_qa(
        self,
        text: str,
        ctx: SessionContext,
    ) -> HandlerResult:
        """商品知识查询：按 context 中的商品 ID 过滤知识库。

        需要 SessionContext.last_focus_product_id 确定商品。
        无商品上下文时追问引导。
        """
        product_id = ctx.last_focus_product_id
        if not product_id:
            return HandlerResult(
                scenario_id="knowledge.product_qa",
                reply="请问您想了解哪款商品的详细信息？",
                pending_directive=PendingDirective.CLEAR,
            )

        result = await self._call_skill(
            "search_knowledge",
            tenant_id=ctx.tenant_id,
            query=text,
            product_id=product_id,
        )
        if not result.ok:
            return HandlerResult(
                scenario_id="knowledge.product_qa",
                reply="暂时无法查询商品知识，请稍后再试。",
                pending_directive=PendingDirective.CLEAR,
            )

        items = (result.result or {}).get("items", [])
        if not items:
            return HandlerResult(
                scenario_id="knowledge.product_qa",
                reply=f"暂未找到该商品的相关信息。",
                pending_directive=PendingDirective.CLEAR,
            )

        return await self._handle_knowledge_hits(text, items, "knowledge.product_qa", ctx.tenant_id)

    async def _try_follow_up(
        self,
        text: str,
        ctx: SessionContext,
        scenario: str,
    ) -> HandlerResult | None:
        """追问路径：在 last_knowledge_refs 范围内精准检索。

        只对 source_type=document 的引用按 doc_id 过滤检索。
        QA 类引用不支持 doc_id 过滤，走降级路径。
        返回 None 表示未命中，交给后续路径处理。
        """
        doc_ids = [
            r["doc_id"] for r in ctx.last_knowledge_refs
            if r.get("source_type") == "document" and r.get("doc_id")
        ]
        if not doc_ids:
            return None

        result = await self._call_skill(
            "search_knowledge",
            tenant_id=ctx.tenant_id,
            query=text,
            doc_ids=doc_ids,
        )
        if not result.ok:
            return None

        items = (result.result or {}).get("items", [])
        if not items:
            return None

        return await self._handle_knowledge_hits(text, items, scenario, ctx.tenant_id)

    async def _handle_knowledge_hits(
        self,
        text: str,
        items: list[dict[str, Any]],
        scenario: str,
        tenant_id: int,
    ) -> HandlerResult:
        """处理知识分块命中：短内容直出，长内容 LLM 摘要。"""
        # 单条短内容 → 直接返回
        if len(items) == 1 and (items[0].get("token_count") or 0) < KNOWLEDGE_SHORT_CONTENT_TOKEN_LIMIT:
            reply = KnowledgeReplyBuilder.knowledge_direct(items)
            return HandlerResult(
                scenario_id=scenario,
                reply=reply,
                pending_directive=PendingDirective.CLEAR,
                context_update={
                    "last_knowledge_topic": text[:80],
                    "last_knowledge_scope": "knowledge",
                    "last_knowledge_refs": _build_knowledge_refs(items, "knowledge"),
                },
            )

        # 多条或长内容 → LLM 摘要
        knowledge_context = "\n\n".join(
            str(item.get("content", "")) for item in items if item.get("content")
        )
        summary = await self._summarize_with_llm(text, knowledge_context, tenant_id)
        reply = KnowledgeReplyBuilder.knowledge_summary(items, summary)
        return HandlerResult(
            scenario_id=scenario,
            reply=reply,
            pending_directive=PendingDirective.CLEAR,
            context_update={
                "last_knowledge_topic": text[:80],
                "last_knowledge_scope": "knowledge",
                "last_knowledge_refs": _build_knowledge_refs(items, "knowledge"),
            },
        )

    # ── 辅助方法 ──

    @staticmethod
    def _is_follow_up(text: str) -> bool:
        """判断是否为追问。

        检查文本是否包含指代关键词。
        """
        return any(kw in text for kw in KNOWLEDGE_DEIXIS_KEYWORDS)

    async def _summarize_with_llm(
        self,
        user_text: str,
        knowledge_context: str,
        tenant_id: int,
    ) -> str:
        """基于知识库内容进行 LLM 摘要。"""
        messages = build_knowledge_summary_messages(user_text, knowledge_context)
        try:
            return await complete(
                use_case=LLMUseCase.RAG_REPLY,
                messages=messages,
                tenant_id=tenant_id,
                temperature=0.2,
            )
        except Exception:
            logger.warning("知识摘要 LLM 失败，降级返回拼接内容: text=%s", user_text[:40])
            return knowledge_context[:500]

    async def _call_skill(
        self,
        method: str,
        **kwargs: Any,
    ) -> ToolResult:
        """调用 Skill 方法（通过 SkillGateway 自动记录 trace + 管理 DB session）。"""
        if self._skill is None:
            import app.ai.skills.knowledge as _real_skill
            self._skill = _real_skill
        try:
            return await call_skill(self._skill, method, **kwargs)
        except SkillError:
            logger.warning("Skill 调用失败: method=%s", method)
            return _empty_tool_result(method)


# ── 工具函数 ──


def _empty_tool_result(method: str) -> ToolResult:
    return ToolResult(ok=False, skill_name=method, error="知识检索服务暂不可用")


def _build_knowledge_refs(
    items: list[dict[str, Any]],
    scope: str,
) -> list[dict[str, Any]]:
    """从检索结果中提取知识引用摘要（最多 5 条）。

    每条引用包含：
      - source_type: "qa" / "document"
      - source_id: 主标识（qa_id / chunk_id）
      - doc_id: 文档 ID
      - chunk_id: 知识块 ID
      - title: 标题
      - content_preview: 内容预览
    """
    refs = []
    for item in items[:5]:
        if scope == "qa":
            ref = {
                "source_type": "qa",
                "source_id": item.get("id", ""),
                "doc_id": "",
                "chunk_id": "",
                "title": item.get("question", "")[:80] or item.get("title", "")[:80],
                "content_preview": _preview(item.get("answer") or "", 100),
            }
        else:
            ref = {
                "source_type": "document",
                "source_id": item.get("id", ""),
                "doc_id": item.get("doc_id", ""),
                "chunk_id": item.get("id", ""),
                "title": item.get("title", "")[:80] or item.get("question", "")[:80],
                "content_preview": _preview(item.get("content") or "", 100),
            }
        if ref["source_id"]:
            refs.append(ref)
    return refs


def _preview(text: str, max_len: int) -> str:
    """截取文本前 max_len 字符作为预览。"""
    return text.strip()[:max_len]
