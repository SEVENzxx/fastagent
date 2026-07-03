"""ProductHandler — 商品场景 Handler。

Handler 编排 ScenarioExtractor → ProductSkill → ProductReplyBuilder。
不直接调用 LLM 或 Vector Search。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.ai.components.extractors import ProductDetailExtractor, ProductFilterExtractor
from app.ai.components.product_reference_resolver import (
    ProductLookup,
    ProductReferenceResolver,
    _is_compare_continuation,
    _parse_ordinal_from_text,
)
from app.ai.context.context_resolver import _is_usage_question
from app.ai.context.pending_state import PendingDirective
from app.ai.context.session_context import SessionContext
from app.ai.handlers.base import BaseHandler, HandlerResult, ToolResult, call_skill_failed
from app.ai.llm.gateway import LLMUseCase, complete
from app.ai.prompts.product_extract import PRODUCT_RECOMMEND_ANALYSIS_PROMPT
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
        knowledge_skill: object = None,
    ) -> None:
        self._skill = skill
        self._resolver = resolver
        self._knowledge_skill = knowledge_skill
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
                result = await self._handle_catalog(text, ctx, decision)
            case SCENARIO.PRODUCT_FILTER_SEARCH:
                result = await self._handle_filter_search(text, ctx, decision)
            case SCENARIO.PRODUCT_SKU_QUERY:
                result = await self._handle_sku_query(text, decision, ctx)
            case SCENARIO.PRODUCT_DETAIL:
                result = await self._handle_detail(text, decision, ctx)
            case SCENARIO.PRODUCT_COMPARE:
                result = await self._handle_compare(text, ctx)
            case SCENARIO.PRODUCT_USAGE:
                result = await self._handle_usage(text, decision, ctx)
            case SCENARIO.PRODUCT_ATTRIBUTE_QUERY:
                result = await self._handle_attribute_query(text, decision, ctx)
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
        decision: ScenarioDecision | None = None,
    ) -> HandlerResult:
        """商品分类浏览。

        首次进入展示分类树，后续通过 category_id 下钻展示商品列表。
        """
        # ── 分类下钻：选中分类后展示该分类下所有商品 ──
        category_id = None
        cat_name = None
        if decision and decision.entities.get("category_id"):
            category_id = decision.entities["category_id"]
            cat_name = decision.entities.get("category_name", "")

        if category_id is not None:
            # 收集所有子分类 ID（含孙子节点）
            all_cat_ids = await self._collect_descendant_category_ids(
                ctx.tenant_id, category_id,
            )
            params = SearchProductParams(category_ids=all_cat_ids, limit=50)
            products = await self._call_skill(
                "search_products", tenant_id=ctx.tenant_id, params=params,
            )
            if not products:
                return HandlerResult(
                    scenario_id=SCENARIO.PRODUCT_CATALOG,
                    reply=ProductReplyBuilder.no_results(cat_name or "该分类"),
                    pending_directive=PendingDirective.CLEAR,
                    context_update={"last_intent": SCENARIO.PRODUCT_CATALOG},
                )

            candidates = [
                {"id": p["id"], "name": p["name"]} for p in products
            ]
            page_size = DEFAULT_PAGE_SIZE
            page_products = products[:page_size]
            has_more = len(products) > page_size
            return HandlerResult(
                scenario_id=SCENARIO.PRODUCT_CATALOG,
                reply=ProductReplyBuilder.product_list(
                    page_products, category=cat_name, show_pagination=has_more,
                ),
                pending_directive=PendingDirective.CLEAR,
                context_update={
                    "product_candidates": candidates,
                    "product_page": 1,
                    "last_visible_products": [
                        {"index": i + 1, "product_id": str(p["id"]), "name": p["name"]}
                        for i, p in enumerate(products)
                    ],
                    "last_intent": SCENARIO.PRODUCT_CATALOG,
                },
            )

        # ── 首次进入：展示分类树 ──
        categories = await self._call_skill("list_categories", tenant_id=ctx.tenant_id)
        reply = ProductReplyBuilder.category_list(categories)

        # 将根分类保存为序号可选的 visible_products，is_category 标记用于 ContextResolver 路由
        cat_items = [
            {
                "index": i + 1,
                "product_id": str(cat["id"]),
                "name": cat["name"],
                "is_category": True,
            }
            for i, cat in enumerate(categories)
        ]

        return HandlerResult(
            scenario_id=SCENARIO.PRODUCT_CATALOG,
            reply=reply,
            pending_directive=PendingDirective.CLEAR,
            context_update={
                "last_visible_products": cat_items,
                "last_intent": SCENARIO.PRODUCT_CATALOG,
            },
        )

    async def _collect_descendant_category_ids(
        self,
        tenant_id: int,
        parent_id: int,
    ) -> list[int]:
        """收集指定分类下所有子分类 ID（含自身和子孙节点）。

        通过 Skill 获取全部分类树后递归收集。
        """
        categories = await self._call_skill("list_categories", tenant_id=tenant_id)

        def _find_node(tree: list[dict], pid: int) -> dict | None:
            for node in tree:
                if int(node["id"]) == pid:
                    return node
                if node.get("children"):
                    found = _find_node(node["children"], pid)
                    if found:
                        return found
            return None

        def _collect_ids(node: dict) -> list[int]:
            ids = [int(node["id"])]
            for child in node.get("children") or []:
                ids.extend(_collect_ids(child))
            return ids

        root_node = _find_node(categories, parent_id)
        if root_node is None:
            return [parent_id]
        return _collect_ids(root_node)

    async def _handle_filter_search(
        self,
        text: str,
        ctx: SessionContext,
        decision: ScenarioDecision | None = None,
    ) -> HandlerResult:
        """商品筛选搜索 — Extractor 抽参数 → Skill 查询 → 模板或LLM推荐。"""
        # ── 0: 列表级分析上下文 — 不重新搜索，直接用 batch_get_detail 拉详情 ──
        if decision and decision.entities.get("analysis_mode") == "list_analysis":
            context_product_ids: list[int] = decision.entities.get("context_product_ids", [])
            if context_product_ids:
                products = await self._call_skill(
                    "batch_get_detail",
                    tenant_id=ctx.tenant_id,
                    product_ids=context_product_ids,
                )
                products = [p for p in products if p]
                if not products:
                    return HandlerResult(
                        scenario_id=SCENARIO.PRODUCT_FILTER_SEARCH,
                        reply="您要查看的商品已不存在。",
                        pending_directive=PendingDirective.CLEAR,
                    )
                reply, visible_products = await self._analysis_reply(text, products)
                return HandlerResult(
                    scenario_id=SCENARIO.PRODUCT_FILTER_SEARCH,
                    reply=reply,
                    pending_directive=PendingDirective.CLEAR,
                    context_update={
                        "product_candidates": [
                            {"id": p["id"], "name": p["name"]} for p in visible_products
                        ],
                        "last_visible_products": [
                            {"index": i + 1, "product_id": str(p["id"]), "name": p["name"]}
                            for i, p in enumerate(visible_products)
                        ],
                        "last_focus_product_id": str(visible_products[0]["id"]) if visible_products else None,
                        "last_product_id": str(visible_products[0]["id"]) if visible_products else None,
                        "last_product_name": visible_products[0]["name"] if visible_products else None,
                        "last_intent": SCENARIO.PRODUCT_FILTER_SEARCH,
                        "last_product_query": text[:200],
                    },
                )
        extract_result = await self._filter_extractor.extract(
            text=text, context=ctx, tenant_id=ctx.tenant_id,
        )
        extracted = extract_result.entities

        # analysis 模式：LLM 兜底分析匹配，不需要 vector reorder
        reply_mode = extracted.get("reply_mode", "template")
        search_query = "" if reply_mode == "analysis" else extracted.get("query_text", "")

        products = await self._call_skill(
            "search_products",
            tenant_id=ctx.tenant_id,
            params=SearchProductParams(
                category_id=extracted.get("category_id"),
                category_ids=extracted.get("category_ids", []),
                min_price=extracted.get("price_min"),
                max_price=extracted.get("price_max"),
                attr_filters=extracted.get("attr_filters") or {},
                query_text=search_query,
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

        page_size = DEFAULT_PAGE_SIZE
        page_products = products[:page_size]
        has_more = len(products) > page_size

        # ── 按 reply_mode 决定回复方式 ──
        if reply_mode == "analysis":
            reply, visible_products = await self._analysis_reply(text, products)
            # 候选缩小为 LLM 推荐子集，确保后续序号引用指向推荐商品而非全量
            candidates = [
                {"id": p["id"], "name": p["name"]} for p in visible_products
            ]
        else:
            reply = ProductReplyBuilder.product_list(
                page_products, header_suffix=suffix, show_pagination=has_more,
            )
            visible_products = products

        return HandlerResult(
            scenario_id=SCENARIO.PRODUCT_FILTER_SEARCH,
            reply=reply,
            pending_directive=PendingDirective.CLEAR,
            context_update={
                "product_candidates": candidates,
                "product_page": 1,
                "last_visible_products": [
                    {"index": i + 1, "product_id": str(p["id"]), "name": p["name"]}
                    for i, p in enumerate(visible_products)
                ],
                "last_focus_product_id": str(visible_products[0]["id"]) if visible_products else None,
                "last_product_id": str(visible_products[0]["id"]) if visible_products else None,
                "last_product_name": visible_products[0]["name"] if visible_products else None,
                "last_product_query": text[:200],
                "last_intent": SCENARIO.PRODUCT_FILTER_SEARCH,
            },
        )


    async def _analysis_reply(
        self,
        text: str,
        products: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        """LLM 分析推荐 — 返回 (回复文本, 推荐的商品列表)。

        LLM 输出结构化 JSON（含 recommended_ids），系统解析后写入 last_visible_products，
        确保后续序号引用指向推荐的子集而非全量搜索结果。
        """
        product_lines = "\n".join(
            f"{i + 1}. {p.get('name', '')} ¥{float(p['price']):.0f} {p.get('description', '')[:80]}"
            for i, p in enumerate(products[:20])
        )
        messages = [
            {"role": "system", "content": PRODUCT_RECOMMEND_ANALYSIS_PROMPT.format(
                user_query=text,
                products=product_lines,
            )},
        ]
        try:
            raw = await complete(
                LLMUseCase.RAG_REPLY,
                messages,
                max_tokens=500,
                temperature=0.3,
            )
            parsed = json.loads(raw.strip())
            recommended_ids: list[int] = parsed.get("recommended_ids", [])
            reply: str = parsed.get("recommendation_reply", "")

            # 校验并过滤出有效推荐
            recommended = []
            seen: set[int] = set()
            for idx in recommended_ids:
                if 1 <= idx <= len(products) and idx not in seen:
                    recommended.append(products[idx - 1])
                    seen.add(idx)

            if reply and recommended:
                return reply, recommended
        except Exception:
            logger.warning(
                "LLM 分析推荐失败，降级为模板: %s", text[:30], exc_info=True,
            )

        # 降级：返回模板列表 + 第一页
        return (
            ProductReplyBuilder.product_list(products[:DEFAULT_PAGE_SIZE]),
            products[:DEFAULT_PAGE_SIZE],
        )

    async def _handle_sku_query(
        self,
        text: str,
        decision: ScenarioDecision,
        ctx: SessionContext,
    ) -> HandlerResult:
        """SKU 精确查询。"""
        sku = str(decision.entities.get("sku") or text or "").strip()
        if not sku:
            return HandlerResult(
                scenario_id=SCENARIO.PRODUCT_SKU_QUERY,
                reply="请提供要查询的 SKU。",
                pending_directive=PendingDirective.CLEAR,
            )

        product = await self._call_skill(
            "search_by_sku",
            tenant_id=ctx.tenant_id,
            sku=sku,
        )
        if product is None:
            return HandlerResult(
                scenario_id=SCENARIO.PRODUCT_SKU_QUERY,
                reply=f"未找到 SKU「{sku}」对应的商品。",
                pending_directive=PendingDirective.CLEAR,
            )

        return HandlerResult(
            scenario_id=SCENARIO.PRODUCT_SKU_QUERY,
            reply=ProductReplyBuilder.product_detail(product),
            pending_directive=PendingDirective.CLEAR,
            context_update={
                "last_product_id": str(product["id"]),
                "last_product_name": product.get("name", ""),
                "last_focus_product_id": str(product["id"]),
                "last_intent": SCENARIO.PRODUCT_SKU_QUERY,
            },
        )

    async def _handle_attribute_query(
        self,
        text: str,
        decision: ScenarioDecision,
        ctx: SessionContext,
    ) -> HandlerResult:
        """商品属性查询。"""
        resolver = self._get_resolver(ctx)
        ref_result = await resolver.resolve(
            text=text,
            entities=decision.entities,
            context=ctx,
            tenant_id=ctx.tenant_id,
        )
        if ref_result.need_clarification:
            return self._clarify_result(SCENARIO.PRODUCT_ATTRIBUTE_QUERY, ref_result, ctx)
        if not ref_result.resolved or ref_result.product_id is None:
            return HandlerResult(
                scenario_id=SCENARIO.PRODUCT_ATTRIBUTE_QUERY,
                reply="请先告诉我您想查询哪款商品的属性。",
                pending_directive=PendingDirective.CLEAR,
            )

        attribute_code = str(decision.entities.get("attribute_code") or "").strip()
        if attribute_code:
            attr = await self._call_skill(
                "get_attribute",
                tenant_id=ctx.tenant_id,
                product_id=ref_result.product_id,
                attribute_code=attribute_code,
            )
            if not attr or attr.get("value") is None:
                reply = f"暂未找到「{ref_result.product_name or ref_result.product_id}」的「{attribute_code}」信息。"
            else:
                reply = (
                    f"{attr.get('product_name') or ref_result.product_name or '该商品'} 的"
                    f"「{attribute_code}」：{attr.get('value')}"
                )
            return HandlerResult(
                scenario_id=SCENARIO.PRODUCT_ATTRIBUTE_QUERY,
                reply=reply,
                pending_directive=PendingDirective.CLEAR,
                context_update={
                    "last_product_id": str(ref_result.product_id),
                    "last_product_name": ref_result.product_name or "",
                    "last_focus_product_id": str(ref_result.product_id),
                    "last_intent": SCENARIO.PRODUCT_ATTRIBUTE_QUERY,
                },
            )

        product = await self._call_skill(
            "get_detail",
            tenant_id=ctx.tenant_id,
            product_id=ref_result.product_id,
        )
        if product is None:
            return HandlerResult(
                scenario_id=SCENARIO.PRODUCT_ATTRIBUTE_QUERY,
                reply=f"商品「{ref_result.product_name or ref_result.product_id}」已下架或不存在。",
                pending_directive=PendingDirective.CLEAR,
            )
        attrs_json = product.get("attrs_json") or {}
        attrs = attrs_json.get("attr") if isinstance(attrs_json.get("attr"), dict) else attrs_json
        return HandlerResult(
            scenario_id=SCENARIO.PRODUCT_ATTRIBUTE_QUERY,
            reply=ProductReplyBuilder.product_attributes(product, attrs),
            pending_directive=PendingDirective.CLEAR,
            context_update={
                "last_product_id": str(product["id"]),
                "last_product_name": product.get("name", ""),
                "last_focus_product_id": str(product["id"]),
                "last_intent": SCENARIO.PRODUCT_ATTRIBUTE_QUERY,
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

        # 单候选 → 统一走 get_detail，避免搜索结果和详情结果口径不一致。
        p = products[0]
        query = entities.get("query", text)
        return await self._detail_by_id(
            int(p["id"]),
            p.get("name"),
            ctx,
            query_text=query,
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
                scenario_id=SCENARIO.PRODUCT_USAGE,
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
        explicit_page = decision.entities.get("page")
        page_size = _safe_int(decision.entities.get("page_size"), DEFAULT_PAGE_SIZE)
        if explicit_page is not None:
            page = max(1, int(explicit_page))
        else:
            # 没有显式页码时根据语义确定翻页方向
            text = ctx.last_user_message or ""
            if any(kw in text for kw in ("下一页", "下页", "更多", "还有")):
                page = ctx.product_page + 1
            elif any(kw in text for kw in ("上一页", "上页", "返回", "前页")):
                page = max(1, ctx.product_page - 1)
            else:
                page = ctx.product_page
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
                    {"id": p["id"], "name": p["name"]} for p in page_products
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
        except Exception:
            logger.warning("Skill 调用异常: method=%s", method, exc_info=True)
            return _SKILL_DEFAULTS.get(method, [])

    async def _detail_by_id(
        self,
        product_id: int,
        product_name: str | None,
        ctx: SessionContext,
        query_text: str = "",
        scenario_id: str = SCENARIO.PRODUCT_DETAIL,
    ) -> HandlerResult:
        """按 product_id 查询详情，含受控知识增强。"""
        product = await self._call_skill(
            "get_detail",
            tenant_id=ctx.tenant_id,
            product_id=product_id,
        )
        if product is None:
            return HandlerResult(
                scenario_id=scenario_id,
                reply=f"商品「{product_name or product_id}」已下架或不存在。",
                pending_directive=PendingDirective.CLEAR,
            )

        reply = await self._build_detail_reply(query_text, product)
        return HandlerResult(
            scenario_id=scenario_id,
            reply=reply,
            pending_directive=PendingDirective.CLEAR,
            context_update={
                "last_product_id": str(product["id"]),
                "last_product_name": product.get("name", ""),
                "last_focus_product_id": str(product["id"]),
                "last_intent": scenario_id,
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
        _ = ctx
        if self._resolver is not None:
            return self._resolver
        self._resolver = ProductReferenceResolver(lookup=_ProductLookup(self))
        return self._resolver

    async def _call_knowledge_skill(
        self,
        method: str,
        **kwargs: Any,
    ) -> ToolResult:
        """调用 KnowledgeSkill，并通过 SkillGateway 记录 trace。"""
        if self._knowledge_skill is None:
            import app.ai.skills.knowledge as _real_knowledge_skill
            self._knowledge_skill = _real_knowledge_skill
        try:
            return await call_skill(self._knowledge_skill, method, **kwargs)
        except SkillError:
            logger.warning("KnowledgeSkill 调用失败: method=%s", method)
            return call_skill_failed(method)
        except Exception:
            logger.warning("KnowledgeSkill 调用异常: method=%s", method, exc_info=True)
            return call_skill_failed(method)

    async def _build_detail_reply(
        self,
        query_text: str,
        product: dict[str, Any],
    ) -> str:
        """按关键词触发产品知识增强，回复生成交给 ReplyBuilder。"""
        query_has_kw = bool(query_text) and any(kw in query_text for kw in _KNOWLEDGE_KEYWORDS)
        if not query_has_kw:
            return ProductReplyBuilder.product_detail(product)
        knowledge = await self._search_product_knowledge(query_text, product)
        return await ProductReplyBuilder.detail_with_knowledge(
            question=query_text,
            product=product,
            knowledge=knowledge,
            force_llm=True,
        )

    async def _search_product_knowledge(
        self,
        text: str,
        product: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """通过 KnowledgeSkill 检索指定商品的知识分块。"""
        result = await self._call_knowledge_skill(
            "search_product_knowledge",
            tenant_id=int(product.get("tenant_id") or 0),
            query=text,
            product_id=str(product.get("id") or ""),
        )
        if not result.ok:
            return []
        payload = result.result if isinstance(result.result, dict) else {}
        return list(payload.get("items") or [])

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


class _ProductLookup(ProductLookup):
    """ProductReferenceResolver 使用的查询端口实现。"""

    def __init__(self, handler: ProductHandler) -> None:
        self._handler = handler

    async def get_detail(self, product_id: int, tenant_id: int) -> dict[str, Any] | None:
        """通过 ProductSkill 校验产品详情。"""
        return await self._handler._call_skill(
            "get_detail",
            tenant_id=tenant_id,
            product_id=product_id,
        )

    async def search(
        self,
        name: str,
        tenant_id: int,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """通过 ProductSkill 搜索产品候选。"""
        return await self._handler._call_skill(
            "search_products",
            tenant_id=tenant_id,
            params=SearchProductParams(product_name=name, limit=limit),
        )


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
