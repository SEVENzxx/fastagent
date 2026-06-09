"""商务主链路决策分流层。

这里只做编排：规则路由 -> 产品咨询或订单动作 -> 返回统一结果。
旧的大状态机逻辑已拆到 reference / flows / replies / skills。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.ai.agent.types import AgentContext
from app.ai.flows.order_action_flow import OrderActionFlow
from app.ai.flows.product_consult_flow import ProductConsultFlow
from app.ai.memory.conversation_state import ConversationCommerceState, ConversationStage
from app.ai.reference.product_reference import (
    match_products_from_candidates,
    normalize_product_reference_text,
)
from app.ai.flows.commerce_rules import route_commerce_message
from app.ai.schemas.commerce_types import ActionType, CommerceRoute, CostLevel, ReplyResult
from app.ai.skills.orders import (
    cancel_order_draft,
    confirm_order,
    create_order_draft,
    manage_order,
    update_draft_order_quantity,
    update_order_draft,
)
from app.ai.skills.products import get_product_detail, list_product_categories, search_products
from app.models.product import Product

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CommerceFlowResult:
    """电商链路结果。"""

    text: str                          # 回复文本
    state: ConversationCommerceState   # 更新后的会话状态
    tool_results: list[dict[str, Any]] # 技能调用记录
    reply: ReplyResult                 # 结构化回复


async def handle_commerce_flow(
    ctx: AgentContext,
    customer_text: str,
    state: ConversationCommerceState,
) -> CommerceFlowResult | None:
    """电商主入口：规则路由 → 分流转发 → 统一返回。未命中交回通用 RAG。"""

    text = customer_text.strip()
    if not text:
        return None

    previous_stage = state.stage                     # 记录进入前的阶段
    decision, slots = route_commerce_message(text, state)  # 1) 规则路由：13 条规则确定方向 + 抽取槽位
    logger.info(
        "电商路由完成：tenant=%s conversation=%s route=%s action=%s risk=%s stage=%s",
        ctx.tenant_id, ctx.conversation_id, decision.route.value,
        decision.action_type, decision.risk_level.value, previous_stage.value,
    )

    # ── 2) 按路由方向分发 ──
    if decision.route == CommerceRoute.GENERAL_RAG:
        logger.info("电商链路未命中，交给通用问答：conversation=%s", ctx.conversation_id)
        return None                                  # 非电商意图，交给通用意图识别管线

    if decision.route == CommerceRoute.FALLBACK and decision.action_type == ActionType.EXIT_FLOW:
        _clear_selection_flow(state)                 # 退出流程 → 清理候选/选品状态
        reply = ReplyResult(
            text="已退出当前选择流程。您可以重新告诉我想咨询的商品、订单或售后问题。",
            response_type="flow_exit",
            route=decision.route,
            risk_level=decision.risk_level,
            cost_level=CostLevel.FREE_RULE,
            metadata={"decision_reason": decision.reason},
        )
        tool_results: list[dict[str, Any]] = []
    elif decision.route == CommerceRoute.PRODUCT_CONSULT:
        reply, tool_results = await _product_flow().handle(ctx, text, state, decision, slots)  # 产品咨询
    elif decision.route == CommerceRoute.ORDER_ACTION:
        reply, tool_results = await _order_flow().handle(ctx, text, state, decision, slots)    # 订单动作
    else:
        return None

    _stamp_reply(reply, decision)                    # 3) 补全路由/风险/动作到 reply
    _apply_context_updates(state, reply.context_updates)  # 4) 同步上下文更新

    # ── 5) 未处理或回复为空 → 交给通用管线 ──
    if not reply.handled:
        logger.info("电商链路显式未处理，交给通用问答：tenant=%s conversation=%s", ctx.tenant_id, ctx.conversation_id)
        return None
    if not reply.text.strip():
        logger.info("电商回复为空，交给通用问答：tenant=%s conversation=%s", ctx.tenant_id, ctx.conversation_id)
        return None

    # ── 6) 更新会话状态：意图、技能、路由、回复类型 ──
    if not state.last_intent:
        state.last_intent = decision.action_type
    if state.last_skill and not state.last_agent_action:
        state.last_agent_action = state.last_skill
    state.last_route = decision.route.value
    state.last_response_type = reply.response_type

    logger.info(
        "电商链路完成：tenant=%s conversation=%s %s->%s route=%s intent=%s skill=%s response=%s",
        ctx.tenant_id, ctx.conversation_id, previous_stage.value, state.stage.value,
        decision.route.value, state.last_intent, state.last_skill or state.last_agent_action, reply.response_type,
    )
    return CommerceFlowResult(reply.text, state, tool_results, reply)


def _stamp_reply(reply: ReplyResult, decision) -> None:
    """把决策结果补到统一 ReplyResult 上，便于 processor 统一写 metadata。"""

    if reply.route is None:
        reply.route = decision.route
    if reply.risk_level is None:
        reply.risk_level = decision.risk_level
    if reply.response_mode is None:
        reply.response_mode = reply.cost_level
    reply.metadata.setdefault("decision_action", decision.action_type)
    reply.metadata.setdefault("decision_reason", decision.reason)


def _apply_context_updates(state: ConversationCommerceState, updates: dict[str, Any]) -> None:
    """集中应用流程返回的上下文更新，避免状态写入散落在 processor。"""

    for key, value in updates.items():
        if hasattr(state, key):
            setattr(state, key, value)


def _clear_selection_flow(state: ConversationCommerceState) -> None:
    """退出当前选品/澄清流程；保留最近商品，方便后续“这款”继续引用。"""

    state.pending_candidates = []
    state.disambiguation_candidates = []
    state.search_candidates = []
    state.last_displayed_candidates = []
    state.last_recommended_products = []
    state.stage = ConversationStage.IDLE
    state.last_intent = "exit_flow"
    state.last_agent_action = "exit_flow"


def _product_flow() -> ProductConsultFlow:
    """构造产品咨询链路。"""

    return ProductConsultFlow(
        search_products=search_products,
        get_product_detail=get_product_detail,
        list_product_categories=list_product_categories,
        find_product_in_text=_find_product_in_text,
    )


def _order_flow() -> OrderActionFlow:
    """构造订单动作链路。"""

    return OrderActionFlow(
        create_order_draft=create_order_draft,
        update_order_draft=update_order_draft,
        update_draft_order_quantity=update_draft_order_quantity,
        confirm_order=confirm_order,
        cancel_order_draft=cancel_order_draft,
        manage_order=manage_order,
        find_product_in_text=_find_product_in_text,
    )


async def _find_product_in_text(ctx: AgentContext, text: str) -> dict[str, Any] | None:
    """按租户商品库做确定性名称匹配。"""

    if not hasattr(ctx.db, "execute"):
        logger.info("商品全局匹配跳过：db 不支持 execute，tenant=%s conversation=%s", ctx.tenant_id, ctx.conversation_id)
        return None

    result = await ctx.db.execute(
        select(Product)
        .where(Product.tenant_id == ctx.tenant_id, Product.is_active.is_(True))
        .order_by(Product.updated_at.desc(), Product.created_at.desc())
        .limit(100)
    )
    products = list(result.scalars().all())
    normalized_query = normalize_product_reference_text(text)
    sorted_products = sorted(products, key=lambda p: len(p.name or ""), reverse=True)

    match = next((product for product in sorted_products if product.name and product.name in text), None)
    if match is None and normalized_query:
        reverse_matches = [
            product
            for product in sorted_products
            if product.name and normalized_query in normalize_product_reference_text(product.name)
        ]
        match = reverse_matches[0] if len(reverse_matches) == 1 else None
    if match is None and normalized_query:
        payloads = [_product_payload(product) for product in sorted_products]
        alias_matches = match_products_from_candidates(normalized_query, payloads)
        if len(alias_matches) == 1:
            logger.info("商品全局别名/模糊匹配命中：query=%s product=%s", normalized_query, alias_matches[0].get("name"))
            return alias_matches[0]

    logger.info(
        "商品全局匹配：tenant=%s conversation=%s matched=%s query=%s",
        ctx.tenant_id,
        ctx.conversation_id,
        bool(match),
        text[:40],
    )
    return _product_payload(match) if match is not None else None


def _product_payload(product: Product) -> dict[str, Any]:
    """ORM 商品对象转为链路使用的基础事实。"""

    return {
        "id": str(product.id),
        "name": product.name,
        "sku": product.sku,
        "price": float(product.price) if product.price else None,
        "stock": product.stock,
        "description": product.description or "",
        "category_id": str(product.category_id) if product.category_id is not None else None,
    }
