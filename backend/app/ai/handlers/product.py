"""ProductHandler — 商品场景 Handler。

Handler 编排 ProductReferenceResolver → ProductSkill → ProductReplyBuilder。
不直接调用 LLM 或 Vector Search。
"""
from __future__ import annotations

import logging

from app.ai.recognition.examples import SCENARIO
import re
from typing import Any

from app.ai.handlers.base import BaseHandler, HandlerResult
from app.ai.context.pending_state import PendingDirective, PendingState
from app.ai.recognition.types import ScenarioDecision
from app.ai.context.session_context import SessionContext
from app.ai.skills.gateway import SkillError, call_skill
from app.common.constants.business import DEFAULT_PAGE_SIZE
from app.ai.skills.products import ProductSkill, SearchProductParams
from app.ai.reply_builders.product import ProductReplyBuilder
from app.ai.components.product_reference_resolver import (
    ProductInfo,
    ProductLookupGateway,
    ProductReferenceResolver,
)

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

# _call_skill 方法安全默认值（DB 不可用时）
_SKILL_DEFAULTS: dict[str, Any] = {
    "list_categories": [],
    "search_products": [],
    "get_detail": None,
    "batch_get_detail": [],
    "get_attribute": None,
    "search_by_sku": None,
}


# ── 默认 ProductSkillGateway（基于 ProductSkill + AsyncSessionLocal） ──


class _ProductSkillGateway(ProductLookupGateway):
    """ProductSkill 实现的网关，在方法内部懒创建 db session。

    当 db 不可用时（无 session_factory），返回 None / 空列表，
    使 resolve 降级为 need_clarification，不抛异常。
    """

    def __init__(self, session_factory: Any = None) -> None:
        self._session_factory = session_factory

    async def validate_product(
        self,
        product_id: int,
        tenant_id: int,
    ) -> ProductInfo | None:
        if not self._session_factory:
            return None
        try:
            async with self._session_factory() as db:
                product = await ProductSkill.get_detail(
                    db=db, tenant_id=tenant_id, product_id=product_id,
                )
        except Exception:
            logger.warning("验证商品 DB 查询失败: product_id=%s tenant_id=%s", product_id, tenant_id)
            return None
        if product is None:
            return None
        return ProductInfo(
            product_id=int(product["id"]),
            name=product.get("name", ""),
            is_active=product.get("is_active", True),
            tenant_id=product.get("tenant_id", tenant_id),
        )

    async def search_by_name(
        self,
        name: str,
        tenant_id: int,
        *,
        limit: int = 10,
    ) -> list[ProductInfo]:
        if not self._session_factory:
            return []
        try:
            async with self._session_factory() as db:
                products = await ProductSkill.search_products(
                    db=db, tenant_id=tenant_id, product_name=name, limit=limit,
                )
        except Exception:
            logger.warning("搜索商品 DB 查询失败: name=%s tenant_id=%s", name[:80], tenant_id)
            return []
        return [
            ProductInfo(
                product_id=int(p["id"]),
                name=p.get("name", ""),
                is_active=p.get("is_active", True),
                tenant_id=p.get("tenant_id", tenant_id),
            )
            for p in products
        ]


_default_product_resolver: ProductReferenceResolver | None = None


def _get_default_product_resolver() -> ProductReferenceResolver:
    """懒创建默认 ProductReferenceResolver（依赖 ProductSkill + AsyncSessionLocal）。"""
    global _default_product_resolver
    if _default_product_resolver is not None:
        return _default_product_resolver
    session_factory = None
    try:
        from app.integrations.database import AsyncSessionLocal
        session_factory = AsyncSessionLocal
    except Exception:
        logger.warning("数据库不可用，ProductReferenceResolver 使用无 DB 降级模式")
    gateway = _ProductSkillGateway(session_factory=session_factory)
    _default_product_resolver = ProductReferenceResolver(gateway)
    return _default_product_resolver


class ProductHandler(BaseHandler):
    """商品查询/筛选/详情/对比 Handler。

    依赖 ProductReferenceResolver 做产品引用解析，
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

    async def execute(
        self,
        decision: ScenarioDecision,
        context: object,
    ) -> HandlerResult:
        """处理商品场景。"""
        ctx: SessionContext = context  # type: ignore[assignment]
        scenario = decision.scenario_id
        text = decision.entities.get("raw_text", "")
        if not text:
            text = getattr(ctx, "last_user_message", "") or ""

        self._init_trace_context(scenario)

        if scenario == SCENARIO.PRODUCT_CATALOG:
            result = await self._handle_catalog(text, ctx)
        elif scenario == SCENARIO.PRODUCT_FILTER_SEARCH:
            result = await self._handle_filter_search(decision, ctx)
        elif scenario == SCENARIO.PRODUCT_DETAIL:
            result = await self._handle_detail(text, decision, ctx)
        elif scenario == SCENARIO.PRODUCT_COMPARE:
            result = await self._handle_compare(text, ctx)
        elif scenario == SCENARIO.PRODUCT_PAGINATION:
            result = await self._handle_pagination_sort(decision, ctx)
        else:
            logger.warning("未处理的商品场景: %s", scenario)
            result = HandlerResult(
                scenario_id=scenario,
                reply="该功能正在开发中，请稍后再试。",
                pending_directive=PendingDirective.CLEAR,
            )

        self._merge_trace_context(result)
        return result

    async def resume(
        self,
        pending: object,
        message: str,
        context: object,
    ) -> HandlerResult:
        """恢复商品 Pending。

        当前支持从多候选追问中恢复（用户回复序号或名称）。
        """
        ctx: SessionContext = context  # type: ignore[assignment]
        psc = pending  # PendingState
        scenario = getattr(psc, "scenario_id", SCENARIO.PRODUCT_DETAIL)

        self._init_trace_context(scenario)

        # 多候选澄清恢复
        resolver = self._get_resolver(ctx)
        ref_result = await resolver.resolve(
            text=message,
            entities={},
            context=ctx,
            tenant_id=ctx.tenant_id,
        )
        if ref_result.resolved:
            if scenario == SCENARIO.PRODUCT_DETAIL:
                result = await self._detail_by_id(
                    ref_result.product_id, ref_result.product_name, ctx,
                )
            else:
                result = None
            if result is not None:
                self._merge_trace_context(result)
                return result

        # 未解析：返回当前的候选追问
        candidates = getattr(psc, "data", {}).get("candidates") or ref_result.candidates
        if candidates:
            formatted = [
                {
                    "index": c.index if not isinstance(c, dict) else c.get("index", i + 1),
                    "name": c.product_name if not isinstance(c, dict) else c.get("name", c.get("product_name", "")),
                }
                for i, c in enumerate(candidates)
            ]
            result = HandlerResult(
                scenario_id=scenario,
                reply=ProductReplyBuilder.clarify_candidates(formatted),
                pending_directive=PendingDirective.KEEP,
            )
        else:
            result = HandlerResult(
                scenario_id=scenario,
                reply="请提供更完整的商品名称或型号。",
                pending_directive=PendingDirective.KEEP,
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
        decision: ScenarioDecision,
        ctx: SessionContext,
    ) -> HandlerResult:
        """商品筛选搜索。"""
        entities = decision.entities
        products = await self._call_skill(
            "search_products",
            tenant_id=ctx.tenant_id,
            params=SearchProductParams(
                query_text=entities.get("raw_text", ""),
                category_text=entities.get("raw_category_text", ""),
                category_id=entities.get("category_id", ""),
                min_price=entities.get("price_min"),
                max_price=entities.get("price_max"),
                attr_filters=entities.get("raw_attrs") or {},
            ),
        )
        if not products:
            return HandlerResult(
                scenario_id=SCENARIO.PRODUCT_FILTER_SEARCH,
                reply=ProductReplyBuilder.no_results(
                    entities.get("raw_category_text", "")
                ),
                pending_directive=PendingDirective.CLEAR,
                context_update={"last_intent": SCENARIO.PRODUCT_FILTER_SEARCH},
            )

        candidates = [
            {"id": p["id"], "name": p["name"]} for p in products
        ]

        # 构建价格过滤提示
        max_p = entities.get("price_max")
        min_p = entities.get("price_min")
        suffix = None
        if max_p is not None and min_p is not None:
            suffix = f"¥{min_p}-¥{max_p}"
        elif max_p is not None:
            suffix = f"¥{max_p}元以下"
        elif min_p is not None:
            suffix = f"¥{min_p}元以上"
        # 用户表达了价格意图（如"便宜""实惠"）但无明确价格范围时补充价格标签
        if suffix is None:
            _price_keywords = ("便宜", "实惠", "性价比", "预算", "优惠", "低价", "经济")
            _raw = entities.get("raw_text", "") or ""
            _cat = entities.get("raw_category_text", "") or ""
            if any(kw in _raw + _cat for kw in _price_keywords):
                suffix = "价格实惠"

        return HandlerResult(
            scenario_id=SCENARIO.PRODUCT_FILTER_SEARCH,
            reply=ProductReplyBuilder.product_list(products, header_suffix=suffix),
            pending_directive=PendingDirective.CLEAR,
            context_update={
                "product_candidates": candidates,
                "last_focus_product_id": None,
                "last_product_id": None,
                "last_intent": SCENARIO.PRODUCT_FILTER_SEARCH,
            },
        )


    async def _handle_detail(
        self,
        text: str,
        decision: ScenarioDecision,
        ctx: SessionContext,
    ) -> HandlerResult:
        """商品详情。"""
        resolver = self._get_resolver(ctx)
        ref_result = await resolver.resolve(
            text=text,
            entities=decision.entities,
            context=ctx,
            tenant_id=ctx.tenant_id,
        )

        if ref_result.need_clarification:
            return self._clarify_result(
                SCENARIO.PRODUCT_DETAIL, ref_result, ctx,
            )

        if ref_result.resolved:
            return await self._detail_by_id(
                ref_result.product_id, ref_result.product_name, ctx,
            )

        return HandlerResult(
            scenario_id=SCENARIO.PRODUCT_DETAIL,
            reply="抱歉，我没有找到您提到的商品，请提供更完整的名称。",
            pending_directive=PendingDirective.CLEAR,
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
                    "last_focus_product_id": str(products[0]["id"]),
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
                "last_focus_product_id": str(products[0]["id"]),
                "last_intent": SCENARIO.PRODUCT_COMPARE,
            },
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
    ) -> HandlerResult:
        """按 product_id 查询详情。"""
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
        return HandlerResult(
            scenario_id=SCENARIO.PRODUCT_DETAIL,
            reply=ProductReplyBuilder.product_detail(product),
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
        """构造多候选追问结果。"""
        reply = ProductReplyBuilder.clarify_candidates(
            [
                {"index": c.index, "name": c.product_name}
                for c in ref_result.candidates
            ]
        ) if ref_result.candidates else ref_result.reason

        pending_state = None
        pending_directive: PendingDirective = PendingDirective.CLEAR
        if ref_result.candidates:
            pending_state = PendingState(
                scenario_id=scenario_id,
                step="choose_product_candidate",
                expected_response_type="ordinal_or_text",
                data={
                    "candidates": [
                        {"id": c.product_id, "name": c.product_name}
                        for c in ref_result.candidates
                    ],
                    "original_query": getattr(ctx, "last_user_message", ""),
                },
                created_at=__import__("datetime").datetime.now(__import__("zoneinfo").ZoneInfo("UTC")),
                expires_at=__import__("datetime").datetime.now(__import__("zoneinfo").ZoneInfo("UTC")),
            )
            # 快速填充 expires_at
            from datetime import datetime, timedelta, timezone
            pending_state.created_at = datetime.now(timezone.utc)
            pending_state.expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
            pending_directive = PendingDirective.SET

        return HandlerResult(
            scenario_id=scenario_id,
            reply=reply,
            pending_directive=pending_directive,
            pending_state=pending_state,
            context_update={"product_candidates": [
                {"id": c.product_id, "name": c.product_name}
                for c in ref_result.candidates
            ]} if ref_result.candidates else {},
        )

    def _get_resolver(self, ctx: SessionContext) -> ProductReferenceResolver:
        """获取或创建 ProductReferenceResolver。"""
        if self._resolver is not None:
            return self._resolver
        # 默认使用 ProductSkill + AsyncSessionLocal 实现的网关
        return _get_default_product_resolver()

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
    from app.ai.components.product_reference_resolver import _is_compare_continuation
    return _is_compare_continuation(text)
