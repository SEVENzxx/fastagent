"""产品咨询链路：只读事实 + 知识库 + 自然回复。"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.ai.agent.types import AgentContext, ToolResult
from app.ai.llm import gateway as llm_gateway
from app.ai.llm.prompts.product_consult import PRODUCT_CONSULT_SYSTEM_PROMPT
from app.ai.rag.query_rewriter import rewrite_product_consult_query
from app.ai.rag.vector_search import VectorDomain, VectorSearchService
from app.ai.reference.product_reference import (
    match_products_from_candidates,
    normalize_product_reference_text,
    parse_selection_indices,
    resolve_product_reference,
)
from app.ai.reference.product_reference import REFERENCE_WORDS as _REFERENCE_WORDS
from app.ai.replies.deterministic_reply import (
    build_candidate_clarification_reply,
    build_product_candidates_reply,
)
from app.ai.memory.conversation_state import ConversationCommerceState, ConversationStage
from app.ai.schemas.commerce_types import ActionType, CostLevel, DecisionResult, ReplyResult, ResponseType, SkillName, SlotResult
from app.integrations.llm_client import LLMUseCase
from app.models.category import Category
from app.models.product import Product

logger = logging.getLogger(__name__)

ProductSkill = Callable[..., Awaitable[ToolResult]]


class ProductConsultFlow:
    """处理商品/服务事实、知识库和自然语言回答。"""

    def __init__(
        self,
        *,
        search_products: ProductSkill,
        get_product_detail: ProductSkill,
        list_product_categories: ProductSkill | None = None,
        find_product_in_text: Callable[[AgentContext, str], Awaitable[dict[str, Any] | None]] | None = None,
        vector_search: VectorSearchService | None = None,
    ) -> None:
        self.search_products = search_products
        self.get_product_detail = get_product_detail
        self.list_product_categories = list_product_categories
        self.find_product_in_text = find_product_in_text
        self.vector_search = vector_search or VectorSearchService()

    async def handle(
        self,
        ctx: AgentContext,
        text: str,
        state: ConversationCommerceState,
        decision: DecisionResult,
        slots: SlotResult,
    ) -> tuple[ReplyResult, list[dict[str, Any]]]:
        """产品咨询入口：对比 / 分类列表 / 商品列表 / 商品引用 → 详情 → LLM 合成。"""
        state.last_user_message = text
        logger.info("产品咨询开始：tenant=%s conversation=%s action=%s text=%s",
                     ctx.tenant_id, ctx.conversation_id, decision.action_type, text[:60])

        # ── 1) 商品对比 ──
        if decision.action_type == ActionType.COMPARE_PRODUCTS:
            return await self._handle_product_compare(ctx, text, state, decision)

        # ── 2) 公司分类总览（"有什么产品"）──
        if self._is_company_category_query(text):
            return await self._handle_category_list(ctx, state)

        # ── 3) 商品列表查询（"有什么耳机"）──
        if self._is_product_list_query(text, slots):
            return await self._handle_product_list(ctx, text, state, slots)

        # ── 4) 商品引用解析：序号 / 名称 / 指代 / 全局搜索 ──
        reference = await resolve_product_reference(
            text, state,
            global_search=lambda query: self._global_product_search(ctx, query),
        )
        if reference.ambiguous:                     # 多个候选 → 让用户选
            logger.info("商品引用有歧义：tenant=%s conversation=%s candidates=%s",
                         ctx.tenant_id, ctx.conversation_id, len(reference.candidates))
            state.pending_candidates = reference.candidates
            state.disambiguation_candidates = reference.candidates
            state.last_displayed_candidates = reference.candidates
            state.last_recommended_products = reference.candidates
            state.last_intent = ActionType.PRODUCT_REFERENCE_AMBIGUOUS
            state.last_skill = None
            state.last_agent_action = ActionType.ASK_PRODUCT_SELECTION
            reply = build_candidate_clarification_reply(reference.candidates)
            reply.cost_level = CostLevel.FREE_RULE
            return reply, []

        # ── 5) 确定商品名：引用结果 → 已选商品 → 指代词兜底(last_product_keyword) ──
        product_name = reference.product_name or slots.product_keyword or ""
        if not product_name and state.selected_product:
            product_name = str(state.selected_product.get("name") or "")
        if not product_name and any(word in text for word in _REFERENCE_WORDS):
            product_name = state.last_product_keyword or ""
            if product_name:
                logger.info("商品引用兜底命中：keyword=%s text=%s", product_name, text[:40])
        if not product_name:                        # 实在找不到 → 让用户说明
            logger.info("商品引用未命中：tenant=%s conversation=%s", ctx.tenant_id, ctx.conversation_id)
            reply = build_candidate_clarification_reply([])
            reply.cost_level = CostLevel.FREE_RULE
            return reply, []

        # ── 6) 查商品详情（DB + Qdrant）──
        result = await self.get_product_detail(
            tenant_id=ctx.tenant_id, contact_id=ctx.contact_id, db=ctx.db,
            product_name=product_name, query=text,
        )
        tool_results = [_tool_dict(result)]
        products = _products_from_result(result)
        logger.info("商品详情查询完成：tenant=%s conversation=%s product=%s count=%s",
                     ctx.tenant_id, ctx.conversation_id, product_name, len(products))
        if len(products) != 1:
            if len(products) > 1:                   # 多个结果 → 让用户选
                state.pending_candidates = products
                state.disambiguation_candidates = products
                state.last_displayed_candidates = products
                state.last_recommended_products = products
                reply = build_candidate_clarification_reply(products)
                reply.cost_level = CostLevel.FREE_RULE
                return reply, tool_results
            return ReplyResult(                     # 0 个结果 → 告知未找到
                text="暂时没找到这款商品。您可以提供更完整的型号或先看相关品类。",
                response_type=ResponseType.FALLBACK, cost_level=CostLevel.FREE_RULE,
            ), tool_results

        # ── 7) 查知识库 + LLM 合成自然回复 ──
        product = products[0]
        self._remember_product(state, product)      # 记住选中商品（供后续"它怎么样"指代）
        facts = await self._search_product_knowledge(ctx, text, product)
        answer = await self._build_llm_answer(ctx, text, product, facts, result)
        state.last_intent = decision.action_type or ActionType.PRODUCT_CONSULT
        state.last_skill = SkillName.GET_PRODUCT_DETAIL
        state.last_agent_action = SkillName.GET_PRODUCT_DETAIL
        cost = CostLevel.FREE_DB if self._is_simple_fact_query(text) else CostLevel.HIGH_LLM
        return ReplyResult(
            text=answer,
            response_type=decision.response_type or ResponseType.PRODUCT_KNOWLEDGE_ANSWER,
            cost_level=cost,
            metadata={"llm_used": cost == CostLevel.HIGH_LLM, "knowledge_hits": len(facts)},
        ), tool_results

    # ── 子流程：公司商品分类总览（"你们有什么产品"）───
    async def _handle_category_list(
        self,
        ctx: AgentContext,
        state: ConversationCommerceState,
    ) -> tuple[ReplyResult, list[dict[str, Any]]]:
        if self.list_product_categories is None:
            return ReplyResult(text="目前可以直接告诉我想看的品类，我帮您查商品。", response_type=ResponseType.FALLBACK), []
        result = await self.list_product_categories(tenant_id=ctx.tenant_id, contact_id=ctx.contact_id, db=ctx.db)
        state.stage = ConversationStage.PRODUCT_BROWSING
        state.last_intent = ActionType.PRODUCT_CATEGORY_OVERVIEW
        state.last_skill = SkillName.LIST_PRODUCT_CATEGORIES
        state.last_agent_action = SkillName.LIST_PRODUCT_CATEGORIES
        message = _message_from_result(result)
        return ReplyResult(
            text=message or "目前还没有配置商品分类。",
            response_type=ResponseType.PRODUCT_CATEGORY_LIST,
            cost_level=CostLevel.FREE_DB,
        ), [_tool_dict(result)]

    # ── 子流程：按分类搜索商品列表（"有什么耳机"）───
    async def _handle_product_list(
        self,
        ctx: AgentContext,
        text: str,
        state: ConversationCommerceState,
        slots: SlotResult,
    ) -> tuple[ReplyResult, list[dict[str, Any]]]:
        category = slots.category or await self._category_from_text(ctx, text)  # 从文本提取分类名
        logger.info(
            "商品列表查询：tenant=%s conversation=%s category=%s",
            ctx.tenant_id,
            ctx.conversation_id,
            category or "<raw_query>",
        )
        query = category or "" if self._is_company_product_overview(text) else category or text
        result = await self.search_products(
            tenant_id=ctx.tenant_id,
            contact_id=ctx.contact_id,
            db=ctx.db,
            category=category or "",
            query=query,
        )
        products = _products_from_result(result)
        logger.info(
            "商品列表查询完成：tenant=%s conversation=%s count=%s",
            ctx.tenant_id,
            ctx.conversation_id,
            len(products),
        )
        state.pending_candidates = products
        state.last_displayed_candidates = products
        state.disambiguation_candidates = []
        state.last_recommended_products = products
        if len(products) == 1:
            self._remember_product(state, products[0])
            state.stage = ConversationStage.PRODUCT_SELECTED
        else:
            state.selected_product = None
            state.stage = ConversationStage.PRODUCT_CANDIDATE_LISTED
        state.last_intent = ActionType.PRODUCT_CATEGORY_QUERY
        state.last_skill = SkillName.SEARCH_PRODUCTS
        state.last_agent_action = SkillName.SEARCH_PRODUCTS
        if category:
            state.last_product_category = category
            state.last_product_keyword = category
        reply = build_product_candidates_reply(products, category=category)
        reply.cost_level = CostLevel.FREE_DB
        return reply, [_tool_dict(result)]

    async def _handle_product_compare(
        self,
        ctx: AgentContext,
        text: str,
        state: ConversationCommerceState,
        decision: DecisionResult,
    ) -> tuple[ReplyResult, list[dict[str, Any]]]:
        products = self._resolve_compare_products(text, state)
        if len(products) < 2:
            logger.info("商品对比缺少对象：tenant=%s conversation=%s count=%s", ctx.tenant_id, ctx.conversation_id, len(products))
            candidates = state.last_displayed_candidates or state.pending_candidates or state.last_recommended_products
            reply = build_candidate_clarification_reply(candidates)
            reply.cost_level = CostLevel.FREE_RULE
            return reply, []

        detail_products: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []
        for product in products[:3]:
            product_name = str(product.get("name") or "")
            result = await self.get_product_detail(
                tenant_id=ctx.tenant_id,
                contact_id=ctx.contact_id,
                db=ctx.db,
                product_name=product_name,
                query=text,
            )
            tool_results.append(_tool_dict(result))
            detail_products.extend(_products_from_result(result)[:1])

        if len(detail_products) < 2:
            return ReplyResult(text="资料中暂未找到足够的商品信息做对比，我可以帮您转人工确认。", response_type=ResponseType.TRANSFER_HUMAN, cost_level=CostLevel.FREE_DB), tool_results

        state.last_intent = ActionType.COMPARE_PRODUCTS
        state.last_skill = SkillName.GET_PRODUCT_DETAIL
        state.last_agent_action = SkillName.GET_PRODUCT_DETAIL
        self._remember_product(state, detail_products[-1])
        logger.info(
            "商品对比完成：tenant=%s conversation=%s count=%s",
            ctx.tenant_id,
            ctx.conversation_id,
            len(detail_products),
        )
        return ReplyResult(
            text=self._build_compare_answer(text, detail_products),
            response_type=decision.response_type or ResponseType.PRODUCT_COMPARE,
            cost_level=CostLevel.FREE_DB,
        ), tool_results

    # ── 工具：查询与当前商品相关的知识库片段 ──
    async def _search_product_knowledge(self, ctx: AgentContext, text: str, product: dict[str, Any]) -> list[dict[str, Any]]:
        product_id = product.get("id")
        query = self._rewrite_product_query(text, product)
        try:
            hits = await self.vector_search.search_text(
                domain=VectorDomain.KNOWLEDGE_CHUNK,
                tenant_id=ctx.tenant_id,
                query=query,
                top_k=settings.AI_PRODUCT_CONSULT_KNOWLEDGE_TOP_K,
                min_score=settings.AI_PRODUCT_CONSULT_KNOWLEDGE_MIN_SCORE,
                filters=None,
            )
        except Exception as exc:
            logger.warning("商品知识库检索失败：tenant=%s product=%s error=%s", ctx.tenant_id, product_id, exc)
            return []
        logger.info(
            "商品知识库检索完成：tenant=%s conversation=%s product=%s raw_query=%s rewritten_query=%s min_score=%s hits=%s top_score=%s used_for_llm=%s",
            ctx.tenant_id,
            ctx.conversation_id,
            product_id,
            text[:80],
            query[:120],
            min_score,
            len(hits),
            hits[0].score if hits else None,
            bool(hits),
        )
        return [
            {
                "content": str(hit.payload.get("text") or ""),
                "score": hit.score,
                "metadata": hit.payload.get("metadata") or {},
            }
            for hit in hits
            if hit.payload.get("text")
        ]

    # ── 工具：基于商品信息 + 知识库 → LLM 合成自然回复 ──
    async def _build_llm_answer(
        self,
        ctx: AgentContext,
        text: str,
        product: dict[str, Any],
        facts: list[dict[str, Any]],
        detail_result: ToolResult,
    ) -> str:
        # 简单事实查询（库存/价格）→ 直接从 DB 数据回答，不调 LLM
        if "库存" in text or "有货" in text:
            stock = product.get("stock")
            if stock is None:
                return "资料中暂未找到这款商品库存的明确说明，我可以帮您转人工确认。"
            return f"{product.get('name')} 当前库存 {stock} 件，库存信息以系统实时数据为准。"

        fact_text = "\n".join(f"- {item['content'][:500]}" for item in facts if item.get("content"))
        product_text = "\n".join(
            [
                f"商品名称：{product.get('name')}",
                f"价格：{product.get('price')}",
                f"库存：{product.get('stock')}",
                f"描述：{product.get('description') or ''}",
            ]
        )
        if not facts:
            fallback = _message_from_result(detail_result)
            return fallback or "资料中暂未找到明确说明，我可以帮您转人工确认。"

        try:
            return await llm_gateway.complete(
                LLMUseCase.GENERAL_REPLY,
                [
                    {"role": "system", "content": PRODUCT_CONSULT_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"用户问题：{text}\n\n"
                            f"商品基础信息：\n{product_text}\n\n"
                            f"知识库事实：\n{fact_text}\n\n"
                            "请基于以上资料回答。"
                        ),
                    },
                ],
                tenant_id=ctx.tenant_id,
                temperature=0.2,
                max_tokens=500,
            )
        except Exception as exc:
            logger.warning("产品咨询 LLM 生成失败：tenant=%s error=%s", ctx.tenant_id, exc)
            return _message_from_result(detail_result) or "资料中暂未找到明确说明，我可以帮您转人工确认。"

    async def _category_from_text(self, ctx: AgentContext, text: str) -> str | None:
        builtin = self._builtin_category_from_text(text)
        if builtin:
            return builtin
        try:
            result = await ctx.db.execute(select(Category.name).where(Category.tenant_id == ctx.tenant_id))
        except Exception:
            names: list[str] = []
        else:
            names = [str(name) for name in result.scalars().all() if name]
        match = next((name for name in sorted(names, key=len, reverse=True) if name in text), None)
        if match:
            return match
        return None

    def _builtin_category_from_text(self, text: str) -> str | None:
        # SaaS 平台层不内置行业品类映射。品类识别优先走租户自己的 Category 数据；
        # 这里保留函数边界，便于后续接入租户自定义同义词表。
        return None

    async def _find_product_in_text(self, ctx: AgentContext, text: str) -> dict[str, Any] | None:
        result = await ctx.db.execute(
            select(Product)
            .where(Product.tenant_id == ctx.tenant_id, Product.is_active.is_(True))
            .order_by(Product.updated_at.desc(), Product.created_at.desc())
            .limit(100)
        )
        products = list(result.scalars().all())
        match = next(
            (product for product in sorted(products, key=lambda p: len(p.name or ""), reverse=True) if product.name and product.name in text),
            None,
        )
        return _product_payload(match) if match is not None else None

    async def _global_product_search(self, ctx: AgentContext, text: str) -> dict[str, Any] | None:
        if self.find_product_in_text is not None:
            return await self.find_product_in_text(ctx, text)
        return await self._find_product_in_text(ctx, text)

    def _is_product_list_query(self, text: str, slots: SlotResult) -> bool:
        if slots.selection_index is not None:
            return False
        if any(word in text for word in ("有哪些", "有什么", "有啥", "给我看看", "看看", "推荐")):
            return True
        return False

    def _is_company_category_query(self, text: str) -> bool:
        if any(word in text for word in ("推荐", "比较好", "哪个好")):
            return False
        return any(word in text for word in ("公司有哪些产品", "你们有哪些产品", "你们公司有哪些产品", "有什么产品", "产品分类"))

    def _is_company_product_overview(self, text: str) -> bool:
        return any(word in text for word in ("公司有什么", "你们有什么", "有什么产品", "产品推荐", "比较好的产品"))

    def _resolve_compare_products(self, text: str, state: ConversationCommerceState) -> list[dict[str, Any]]:
        candidates = state.pending_candidates or state.last_recommended_products
        pending = [dict(item) for item in candidates if isinstance(item, dict)]
        products: list[dict[str, Any]] = []

        for index in parse_selection_indices(text):
            if 0 <= index < len(pending):
                products.append(pending[index])

        if len(products) >= 2:
            return _dedupe_products(products)

        for part in re.split(r"[和与、,，\s]+", text):
            query = normalize_product_reference_text(part)
            matches = match_products_from_candidates(query, pending)
            if len(matches) == 1:
                products.append(matches[0])

        return _dedupe_products(products)

    def _build_compare_answer(self, text: str, products: list[dict[str, Any]]) -> str:
        lines = ["我按现有商品资料帮您对比："]
        for product in products:
            parts = [str(product.get("name") or "商品")]
            if product.get("price") is not None:
                parts.append(f"价格 ¥{float(product['price']):.2f}")
            if product.get("stock") is not None:
                parts.append(f"库存 {product['stock']}")
            if product.get("description"):
                parts.append(str(product["description"]))
            lines.append("- " + "，".join(parts))

        lines.append("如果您告诉我更关注的点，比如预算、使用场景或规格参数，我可以继续基于商家资料帮您缩小选择。")
        return "\n".join(lines)

    # ── 工具：记住用户当前关注/选中的商品，供后续"它"/"这款"指代 ──
    def _remember_product(self, state: ConversationCommerceState, product: dict[str, Any]) -> None:
        state.selected_product = product
        if product.get("id") is not None:
            state.selected_product_id = str(product["id"])
            state.last_product_id = str(product["id"])
        state.last_product_keyword = str(product.get("name") or "")
        state.stage = ConversationStage.PRODUCT_SELECTED

    # ── 工具：判断是否为简单事实查询（无需 LLM）──
    def _is_simple_fact_query(self, text: str) -> bool:
        return any(word in text for word in ("库存", "有货", "价格", "多少钱")) and not any(
            word in text for word in ("适合", "推荐", "对比", "区别", "详细", "介绍")
        )

    def _rewrite_product_query(self, text: str, product: dict[str, Any]) -> str:
        return rewrite_product_consult_query(text, str(product.get("name") or ""))


def _products_from_result(result: ToolResult) -> list[dict[str, Any]]:
    payload = result.result if isinstance(result.result, dict) else {}
    if isinstance(payload.get("products"), list):
        return [dict(item) for item in payload["products"] if isinstance(item, dict)]
    if isinstance(payload.get("product"), dict):
        return [dict(payload["product"])]
    return []


def _message_from_result(result: ToolResult) -> str:
    if isinstance(result.result, dict) and result.result.get("message"):
        return str(result.result["message"])
    if isinstance(result.result, str):
        return result.result
    return result.error or ""


def _tool_dict(result: ToolResult) -> dict[str, Any]:
    return {"skill_name": result.skill_name, "ok": result.ok, "result": result.result, "error": result.error}


def _product_payload(product: Product) -> dict[str, Any]:
    return {
        "id": str(product.id),
        "name": product.name,
        "sku": product.sku,
        "price": float(product.price) if product.price else None,
        "stock": product.stock,
        "description": product.description or "",
        "category_id": str(product.category_id) if product.category_id is not None else None,
    }


def _dedupe_products(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for product in products:
        key = str(product.get("id") or product.get("name") or "")
        if key and key not in seen:
            seen.add(key)
            result.append(product)
    return result



