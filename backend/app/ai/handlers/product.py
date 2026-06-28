"""ProductHandler — 商品场景 Handler。

Handler 编排 ScenarioExtractor → ProductSkill → ProductReplyBuilder。
不直接调用 LLM 或 Vector Search。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.ai.components.extractors import ProductDetailExtractor, ProductFilterExtractor
from app.ai.components.product_reference_resolver import (
    ProductReferenceResolver,
    _is_compare_continuation,
    _parse_ordinal_from_text,
)
from app.ai.context.context_resolver import _is_usage_question
from app.ai.context.pending_state import PendingDirective
from app.ai.context.session_context import SessionContext
from app.ai.handlers.base import BaseHandler, HandlerResult
from app.ai.recognition.examples import SCENARIO
from app.ai.recognition.types import ScenarioDecision
from app.ai.reply_builders.product import ProductReplyBuilder
from app.ai.skills.gateway import SkillError, call_skill
from app.ai.skills.products import ProductSkill, SearchProductParams
from app.common.constants.business import DEFAULT_PAGE_SIZE

logger = logging.getLogger(__name__)

# 双商品对比正则：第一款和第二款、第1个和第3个
_RE_TWO_ORDINALS = re.compile(
    r"第\s*([一二两三四五六七八九十\d]+)\s*[款个]\s*(?:和|与|跟)\s*第\s*([一二两三四五六七八九十\d]+)\s*[款个]"
)

# 中文数字映射
_CN_NUM_MAP: dict[str, int] = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

# 知识触发关键词：命中后从向量库检索产品知识
_KNOWLEDGE_KEYWORDS: frozenset[str] = frozenset({
    "介绍", "功能", "卖点", "优势", "缺点", "怎么样", "适合", "送人",
    "质量", "好用", "靠谱", "场景", "人群", "评价", "优缺点", "详细",
})


# _call_skill 方法安全默认值（DB 不可用时）
_SKILL_DEFAULTS: dict[str, Any] = {
    "list_categories": [],
    "search_products": [],
    "get_detail": None,
    "batch_get_detail": [],
    "get_attribute": None,
    "search_by_sku": None,
}


class ProductHandler(BaseHandler):
    """商品查询/筛选/详情/对比 Handler。

    依赖 ScenarioExtractor 做参数抽取，
    依赖 ProductSkill 做产品数据查询，
    依赖 ProductReplyBuilder 做回复渲染。
    """

    def __init__(
        self,
        skill: type[ProductSkill] = ProductSkill,
        resolver: ProductReferenceResolver | None = None,
    ) -> None:
        self._skill = skill
        self._resolver = resolver
        self._detail_extractor = ProductDetailExtractor()
        self._filter_extractor = ProductFilterExtractor()

    async def execute(
        self,
        decision: ScenarioDecision,
        context: object,
    ) -> HandlerResult:
        """处理商品场景。"""
        ctx: SessionContext = context  # type: ignore[assignment]
        scenario = decision.scenario_id
        text = ctx.last_user_message or str(decision.entities.get("raw_text") or "")

        self._init_trace_context(scenario)

        match scenario:
            case SCENARIO.PRODUCT_CATALOG:
                result = await self._handle_catalog(text, ctx)
            case SCENARIO.PRODUCT_FILTER_SEARCH:
                result = await self._handle_filter_search(text, ctx)
            case SCENARIO.PRODUCT_DETAIL:
                result = await self._handle_detail(text, decision, ctx)
            case SCENARIO.PRODUCT_COMPARE:
                result = await self._handle_compare(text, ctx)
            case SCENARIO.PRODUCT_USAGE:
                result = await self._handle_usage(text, decision, ctx)
            case SCENARIO.PRODUCT_PAGINATION:
                result = await self._handle_pagination_sort(decision, ctx)
            case _:
                logger.warning("未处理的商品场景: %s", scenario)
                result = HandlerResult(
                    scenario_id=scenario,
                    reply="该功能正在开发中，请稍后再试。",
                    pending_directive=PendingDirective.CLEAR,
                )

        self._merge_trace_context(result)
        return result

    # ── 场景处理方法 ──

    async def _handle_catalog(
        self,
        text: str,
        ctx: SessionContext,
    ) -> HandlerResult:
        """商品分类浏览。"""
        categories = await self._call_skill("list_categories", tenant_id=ctx.tenant_id)
        reply = ProductReplyBuilder.category_list(categories)
        return HandlerResult(
            scenario_id=SCENARIO.PRODUCT_CATALOG,
            reply=reply,
            pending_directive=PendingDirective.CLEAR,
            context_update={
                "last_intent": SCENARIO.PRODUCT_CATALOG,
            },
        )

    async def _handle_filter_search(
        self,
        text: str,
        ctx: SessionContext,
    ) -> HandlerResult:
        """商品筛选搜索 — Extractor 抽参数 → Skill 查询。"""
        extract_result = await self._filter_extractor.extract(
            text=text, context=ctx, tenant_id=ctx.tenant_id,
        )
        extracted = extract_result.entities

        products = await self._call_skill(
            "search_products",
            tenant_id=ctx.tenant_id,
            params=SearchProductParams(
                category_id=extracted.get("category_id"),
                min_price=extracted.get("price_min"),
                max_price=extracted.get("price_max"),
                attr_filters=extracted.get("attr_filters") or {},
            ),
        )
        if not products:
            cat_name = extracted.get("category_name", "")
            return HandlerResult(
                scenario_id=SCENARIO.PRODUCT_FILTER_SEARCH,
                reply=ProductReplyBuilder.no_results(cat_name),
                pending_directive=PendingDirective.CLEAR,
                context_update={"last_intent": SCENARIO.PRODUCT_FILTER_SEARCH},
            )

        candidates = [
            {"id": p["id"], "name": p["name"]} for p in products
        ]

        # 构建价格过滤提示
        max_p = extracted.get("price_max")
        min_p = extracted.get("price_min")
        suffix = None
        if max_p is not None and min_p is not None:
            suffix = f"¥{min_p}-¥{max_p}"
        elif max_p is not None:
            suffix = f"¥{max_p}元以下"
        elif min_p is not None:
            suffix = f"¥{min_p}元以上"
        if suffix is None:
            _price_keywords = ("便宜", "实惠", "性价比", "预算", "优惠", "低价", "经济")
            if any(kw in text for kw in _price_keywords):
                suffix = "价格实惠"
        return HandlerResult(
            scenario_id=SCENARIO.PRODUCT_FILTER_SEARCH,
            reply=ProductReplyBuilder.product_list(products, header_suffix=suffix),
            pending_directive=PendingDirective.CLEAR,
            context_update={
                "product_candidates": candidates,
                "last_visible_products": [
                    {"index": i + 1, "product_id": str(p["id"]), "name": p["name"]}
                    for i, p in enumerate(products)
                ],
                "last_focus_product_id": None,
                "last_product_id": None,
                "last_product_query": text[:200],
                "last_intent": SCENARIO.PRODUCT_FILTER_SEARCH,
            },
        )


    async def _handle_detail(
        self,
        text: str,
        decision: ScenarioDecision,
        ctx: SessionContext,
    ) -> HandlerResult:
        """商品详情 — 先用 Extractor 解析引用，再按结果分流。"""
        # ── 1: Extractor 解析 —— 识别指代/上下文/显式商品名 ──
        extract_result = await self._detail_extractor.extract(
            text=text, context=ctx, tenant_id=ctx.tenant_id,
        )
        entities = extract_result.entities

        # ── 2: 有明确 product_id（指代/上下文）→ 直接查详情 ──
        pid = entities.get("product_id")
        if pid is not None:
            return await self._detail_by_id(int(pid), entities.get("product_name"), ctx, query_text=text)

        # ── 2.5: 裸序号 → 从候选列表解析或澄清，不走 LLM 搜索 ──
        ordinal = _parse_ordinal_from_text(text)
        if ordinal is not None:
            candidates = self._get_candidates(ctx)
            if not candidates:
                return HandlerResult(
                    scenario_id=SCENARIO.PRODUCT_DETAIL,
                    reply="当前没有商品列表，无法使用序号选择。请直接输入商品名称或型号。",
                    pending_directive=PendingDirective.CLEAR,
                )
            if 1 <= ordinal <= len(candidates):
                target = candidates[ordinal - 1]
                result = await self._detail_by_id(
                    int(target["id"]), target["name"], ctx, query_text=text,
                )
                # 候选列表仍保留在 SessionContext 中，便于继续按序号浏览。
                return result
            return HandlerResult(
                scenario_id=SCENARIO.PRODUCT_DETAIL,
                reply=f"序号 {ordinal} 超出商品列表范围（共 {len(candidates)} 个），请重新选择。",
                pending_directive=PendingDirective.CLEAR,
            )

        # ── 3: 用提取的商品名搜索 ──
        search_name = entities.get("product_name_hint", text)
        products = await self._call_skill(
            "search_products",
            tenant_id=ctx.tenant_id,
            params=SearchProductParams(product_name=search_name, limit=10),
        )

        # 无匹配
        if not products:
            return HandlerResult(
                scenario_id=SCENARIO.PRODUCT_DETAIL,
                reply=f"未找到匹配「{search_name}」的产品",
                pending_directive=PendingDirective.CLEAR,
            )

        # 多候选 → 让用户确认
        if len(products) > 1:
            candidates = [{"id": p["id"], "name": p.get("name", "")} for p in products]
            reply = ProductReplyBuilder.product_list(products)
            return HandlerResult(
                scenario_id=SCENARIO.PRODUCT_DETAIL,
                reply=reply,
                pending_directive=PendingDirective.CLEAR,
                context_update={
                    "product_candidates": candidates,
                    "last_visible_products": [
                        {"index": i + 1, "product_id": str(p["id"]), "name": p.get("name", "")}
                        for i, p in enumerate(products)
                    ],
                    "last_intent": SCENARIO.PRODUCT_DETAIL,
                },
            )

        # 单候选 → 展示详情（含知识检索）
        p = products[0]
        query = entities.get("query", text)
        knowledge = await self._fetch_knowledge_if_needed(query, p)
        query_has_kw = bool(query) and any(kw in query for kw in _KNOWLEDGE_KEYWORDS)
        if knowledge:
            reply = await self._generate_knowledge_reply(query, p, knowledge)
        elif query_has_kw:
            reply = await self._generate_knowledge_reply(query, p, [])
        else:
            reply = ProductReplyBuilder.product_detail(p)

        return HandlerResult(
            scenario_id=SCENARIO.PRODUCT_DETAIL,
            reply=reply,
            pending_directive=PendingDirective.CLEAR,
            context_update={
                "last_product_id": str(p["id"]),
                "last_product_name": p.get("name", ""),
                "last_focus_product_id": str(p["id"]),
                "last_intent": SCENARIO.PRODUCT_DETAIL,
            },
        )

    async def _handle_compare(
        self,
        text: str,
        ctx: SessionContext,
    ) -> HandlerResult:
        """商品对比。

        支持两种模式：
          1. 双商品引用："第一款和第二款有什么区别"
          2. 对比延续："和第三款又有什么区别"（使用 compare_base_product_id）
        """
        resolver = self._get_resolver(ctx)

        # 模式 1：双序号对比
        ids = self._parse_two_ordinals(text) if not _is_compare_only(text) else None
        if ids:
            candidates = self._get_candidates(ctx)
            if not candidates or ids[0] > len(candidates) or ids[1] > len(candidates):
                return HandlerResult(
                    scenario_id=SCENARIO.PRODUCT_COMPARE,
                    reply="序号超出商品列表范围，请重新选择。",
                    pending_directive=PendingDirective.CLEAR,
                )
            p0, p1 = candidates[ids[0] - 1], candidates[ids[1] - 1]
            products = await self._call_skill(
                "batch_get_detail",
                tenant_id=ctx.tenant_id,
                product_ids=[_get_candidate_id(p0), _get_candidate_id(p1)],
            )
            if len(products) < 2:
                return HandlerResult(
                    scenario_id=SCENARIO.PRODUCT_COMPARE,
                    reply="对比的商品已下架或不可见，请重新选择。",
                    pending_directive=PendingDirective.CLEAR,
                )
            return HandlerResult(
                scenario_id=SCENARIO.PRODUCT_COMPARE,
                reply=ProductReplyBuilder.compare_result(products),
                pending_directive=PendingDirective.CLEAR,
                context_update={
                    "compare_base_product_id": str(products[0]["id"]),
                    "compare_product_ids": [str(p["id"]) for p in products],
                    "last_intent": SCENARIO.PRODUCT_COMPARE,
                },
            )

        # 模式 2：对比延续 — 解析目标商品
        ref_result = await resolver.resolve(
            text=text,
            entities={},
            context=ctx,
            tenant_id=ctx.tenant_id,
        )

        if ref_result.need_clarification:
            return self._clarify_result(
                SCENARIO.PRODUCT_COMPARE, ref_result, ctx,
            )

        if not ref_result.resolved:
            return HandlerResult(
                scenario_id=SCENARIO.PRODUCT_COMPARE,
                reply="请先查看商品列表，再选择要对比的商品。",
                pending_directive=PendingDirective.CLEAR,
            )

        # 获取基准商品
        base_id = ctx.compare_base_product_id or ctx.last_focus_product_id
        if not base_id:
            return HandlerResult(
                scenario_id=SCENARIO.PRODUCT_COMPARE,
                reply="请先选择一款基准商品，再选择要对比的商品。",
                pending_directive=PendingDirective.CLEAR,
            )

        products = await self._call_skill(
            "batch_get_detail",
            tenant_id=ctx.tenant_id,
            product_ids=[int(base_id), ref_result.product_id],
        )
        if len(products) < 2:
            return HandlerResult(
                scenario_id=SCENARIO.PRODUCT_COMPARE,
                reply="对比的商品已下架或不可见，请重新选择。",
                pending_directive=PendingDirective.CLEAR,
            )
        return HandlerResult(
            scenario_id=SCENARIO.PRODUCT_COMPARE,
            reply=ProductReplyBuilder.compare_result(products),
            pending_directive=PendingDirective.CLEAR,
            context_update={
                "compare_base_product_id": str(products[0]["id"]),
                "compare_product_ids": [str(p["id"]) for p in products],
                "last_intent": SCENARIO.PRODUCT_COMPARE,
            },
        )

    async def _handle_usage(
        self,
        text: str,
        decision: ScenarioDecision,
        ctx: SessionContext,
    ) -> HandlerResult:
        """商品适用性咨询（product.usage）。

        从 decision.entities（ContextResolver 设置）或 Extractor 获取 product_id，
        查商品详情 + 知识库后生成回复。
        """
        pid = decision.entities.get("product_id")
        product_name = decision.entities.get("product_name", "")

        # 没有 product_id → 尝试 extractor
        if pid is None:
            extract_result = await self._detail_extractor.extract(
                text=text, context=ctx, tenant_id=ctx.tenant_id,
            )
            pid = extract_result.entities.get("product_id")
            product_name = extract_result.entities.get("product_name", "")

        if pid is not None:
            return await self._detail_by_id(
                int(pid), product_name, ctx, query_text=text,
            )

        return HandlerResult(
            scenario_id=SCENARIO.PRODUCT_USAGE,
            reply="请先告诉我您想了解哪款商品。",
            pending_directive=PendingDirective.CLEAR,
        )

    async def _handle_pagination_sort(
        self,
        decision: ScenarioDecision,
        ctx: SessionContext,
    ) -> HandlerResult:
        """分页/排序。

        从上下文的 product_candidates 中读取候选，
        按 sort_by / sort_order / page 参数处理，分页展示。
        """
        sort_by = decision.entities.get("sort_by", "")
        sort_order = decision.entities.get("sort_order", "asc")
        page = _safe_int(decision.entities.get("page"), ctx.product_page)
        page_size = _safe_int(decision.entities.get("page_size"), DEFAULT_PAGE_SIZE)
        page = max(1, page)
        page_size = max(1, min(page_size, DEFAULT_PAGE_SIZE * 2))

        raw_candidates = self._get_candidates(ctx)
        if not raw_candidates:
            return HandlerResult(
                scenario_id=SCENARIO.PRODUCT_PAGINATION,
                reply="请先搜索或浏览商品，再进行排序或翻页。",
                pending_directive=PendingDirective.CLEAR,
            )

        product_ids = [_get_candidate_id(c) for c in raw_candidates]
        products = await self._call_skill(
            "batch_get_detail",
            tenant_id=ctx.tenant_id,
            product_ids=product_ids,
        )

        # 排序
        if sort_by == "price":
            reverse = sort_order.lower() != "asc"
            products.sort(key=lambda p: float(p.get("price", 0) or 0), reverse=reverse)
        elif sort_by == "name":
            reverse = sort_order.lower() != "asc"
            products.sort(key=lambda p: p.get("name", ""), reverse=reverse)

        # 分页
        total = len(products)
        total_pages = max(1, (total + page_size - 1) // page_size)
        if page < 1:
            page = 1
        elif page > total_pages:
            page = total_pages
        start = (page - 1) * page_size
        page_products = products[start:start + page_size]

        reply = ProductReplyBuilder.product_list(page_products, show_pagination=total > page_size)
        return HandlerResult(
            scenario_id=SCENARIO.PRODUCT_PAGINATION,
            reply=reply,
            pending_directive=PendingDirective.CLEAR,
            context_update={
                "product_candidates": [
                    {"id": p["id"], "name": p["name"]} for p in products
                ],
                "product_page": page,
                "last_intent": SCENARIO.PRODUCT_PAGINATION,
            },
        )

    # ── 内部方法 ──

    async def _call_skill(
        self,
        method: str,
        **kwargs: Any,
    ) -> Any:
        """调用 Skill 方法（通过 SkillGateway 自动记录 trace + 管理 DB session）。"""
        try:
            return await call_skill(self._skill, method, **kwargs)
        except SkillError:
            logger.warning("Skill 调用失败: method=%s", method)
            return _SKILL_DEFAULTS.get(method, [])

    async def _detail_by_id(
        self,
        product_id: int,
        product_name: str | None,
        ctx: SessionContext,
        query_text: str = "",
    ) -> HandlerResult:
        """按 product_id 查询详情，含知识检索。"""
        product = await self._call_skill(
            "get_detail",
            tenant_id=ctx.tenant_id,
            product_id=product_id,
        )
        if product is None:
            return HandlerResult(
                scenario_id=SCENARIO.PRODUCT_DETAIL,
                reply=f"商品「{product_name or product_id}」已下架或不存在。",
                pending_directive=PendingDirective.CLEAR,
            )

        # 知识检索（含用法/适用性等关键词匹配）
        knowledge = await self._fetch_knowledge_if_needed(query_text, product)
        query_has_kw = bool(query_text) and any(kw in query_text for kw in _KNOWLEDGE_KEYWORDS)
        if knowledge:
            reply = await self._generate_knowledge_reply(query_text, product, knowledge)
        elif query_has_kw:
            # 关键词命中但向量库无数据 → LLM 根据商品属性生成回复
            reply = await self._generate_knowledge_reply(query_text, product, [])
        else:
            reply = ProductReplyBuilder.product_detail(product)

        return HandlerResult(
            scenario_id=SCENARIO.PRODUCT_DETAIL,
            reply=reply,
            pending_directive=PendingDirective.CLEAR,
            context_update={
                "last_product_id": str(product["id"]),
                "last_product_name": product.get("name", ""),
                "last_focus_product_id": str(product["id"]),
                "last_intent": SCENARIO.PRODUCT_DETAIL,
            },
        )


    def _clarify_result(
        self,
        scenario_id: str,
        ref_result: Any,
        ctx: SessionContext,
    ) -> HandlerResult:
        """构造多候选追问结果，并把候选写入 SessionContext。"""
        candidates = [
            {"id": c.product_id, "name": c.product_name}
            for c in ref_result.candidates
        ]
        reply = ProductReplyBuilder.clarify_candidates(
            [
                {"index": c.index, "name": c.product_name}
                for c in ref_result.candidates
            ]
        ) if ref_result.candidates else ref_result.reason

        context_update = {}
        if candidates:
            context_update = {
                "product_candidates": candidates,
                "last_visible_products": [
                    {"index": i + 1, "product_id": str(c["id"]), "name": c["name"]}
                    for i, c in enumerate(candidates)
                ],
                "last_intent": scenario_id,
            }

        return HandlerResult(
            scenario_id=scenario_id,
            reply=reply,
            pending_directive=PendingDirective.CLEAR,
            context_update=context_update,
        )

    def _get_resolver(self, ctx: SessionContext) -> ProductReferenceResolver:
        """获取或创建 ProductReferenceResolver。"""
        if self._resolver is not None:
            return self._resolver
        self._resolver = ProductReferenceResolver()
        return self._resolver

    @staticmethod
    async def _fetch_knowledge_if_needed(text: str, product: dict[str, Any]) -> list[dict[str, Any]] | None:
        """检测知识关键词 → 向量检索该产品的知识库数据。"""
        if not any(kw in text for kw in _KNOWLEDGE_KEYWORDS):
            return None
        try:
            from app.ai.rag.vector_search import VectorDomain, VectorSearchService
            vs = VectorSearchService()
            hits = await vs.search_text(
                domain=VectorDomain.KNOWLEDGE_CHUNK,
                tenant_id=product.get("tenant_id", 0),
                query=text,
                top_k=5,
                filters={"product_id": str(product["id"])},
            )
            return [
                {"content": h.payload.get("content", "")[:120]}
                for h in hits if h.payload.get("content")
            ] if hits else None
        except Exception:
            logger.warning("知识检索失败: product_id=%s", product.get("id"))
            return None

    @staticmethod
    async def _generate_knowledge_reply(
        question: str, product: dict[str, Any], knowledge: list[dict[str, Any]],
    ) -> str:
        """将产品详情 + 知识库数据 + 用户问题交给 LLM 生成回复。"""
        from app.ai.llm.gateway import complete
        from app.ai.prompts.product_knowledge_qa import build_messages
        from app.integrations.llm_client import LLMUseCase

        try:
            raw = await complete(
                LLMUseCase.RAG_REPLY,
                build_messages(question, product, knowledge),
                tenant_id=product.get("tenant_id"),
                max_tokens=400,
                temperature=0.3,
            )
            return raw.strip() if raw else ProductReplyBuilder.product_detail(product)
        except Exception:
            logger.warning("LLM 知识回复生成失败，降级为产品详情模板")
            return ProductReplyBuilder.product_detail(product)

    def _get_candidates(self, ctx: SessionContext) -> list[dict[str, Any]]:
        """从上下文获取候选列表，统一为 {id, name} 格式。"""
        raw = ctx.product_candidates
        if not raw and ctx.active_product_ids and ctx.active_product_names:
            raw = [
                {"id": pid, "name": name}
                for pid, name in zip(ctx.active_product_ids, ctx.active_product_names)
            ]
        if not raw:
            return []
        # 归一化：确保 id/name 键名兼容
        return [
            {"id": str(_get_candidate_id(c)), "name": _get_candidate_name(c)}
            for c in raw
        ]

    @staticmethod
    def _parse_two_ordinals(text: str) -> tuple[int, int] | None:
        """解析双序号，如第一款和第二款 → (1, 2)。"""
        m = _RE_TWO_ORDINALS.search(text)
        if not m:
            return None
        def _to_int(s: str) -> int:
            s = s.strip()
            return int(s) if s.isdigit() else _CN_NUM_MAP.get(s, 0)
        return (_to_int(m.group(1)), _to_int(m.group(2)))


def _safe_int(value: object, default: int = 1) -> int:
    """安全转 int，解析失败返回默认值。"""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_candidate_id(candidate: dict[str, Any]) -> int:
    """从候选字典中提取 ID，兼容 id/product_id 格式。"""
    raw = candidate.get("id") or candidate.get("product_id", 0)
    return int(raw)


def _get_candidate_name(candidate: dict[str, Any]) -> str:
    """从候选字典中提取名称，兼容 name/product_name 格式。"""
    return candidate.get("name") or candidate.get("product_name", "")


def _is_compare_only(text: str) -> bool:
    """判断是否为纯对比延续（和X比），而非双商品引用。"""
    # "第一款和第二款有什么区别" → 双商品
    # "和第三款比" → 对比延续
    if _RE_TWO_ORDINALS.search(text):
        return False
    return _is_compare_continuation(text)
