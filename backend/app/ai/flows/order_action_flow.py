"""订单动作链路：所有写操作必须通过 Skill。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TYPE_CHECKING

from sqlalchemy import select

from app.ai.agent.types import AgentContext, ToolResult
from app.ai.memory.conversation_state import ConversationCommerceState, ConversationStage
from app.ai.reference.product_reference import resolve_product_reference
from app.ai.replies.deterministic_reply import build_candidate_clarification_reply, build_order_reply
from app.ai.schemas.commerce_types import ActionType, DecisionResult, ReplyResult, ResponseType, RiskLevel, SkillName, SkillResult, SlotResult
from app.models.product import Product

logger = logging.getLogger(__name__)

OrderSkill = Callable[..., Awaitable[ToolResult]]


class OrderActionFlow:
    """处理下单、改数量、补信息、确认、取消和查单。"""

    def __init__(
        self,
        *,
        create_order_draft: OrderSkill,
        update_order_draft: OrderSkill,
        update_draft_order_quantity: OrderSkill,
        confirm_order: OrderSkill,
        cancel_order_draft: OrderSkill,
        manage_order: OrderSkill | None = None,
        find_product_in_text: Callable[[AgentContext, str], Awaitable[dict[str, Any] | None]] | None = None,
    ) -> None:
        self.create_order_draft = create_order_draft
        self.update_order_draft = update_order_draft
        self.update_draft_order_quantity = update_draft_order_quantity
        self.confirm_order = confirm_order
        self.cancel_order_draft = cancel_order_draft
        self.manage_order = manage_order
        self.find_product_in_text = find_product_in_text

    async def handle(
        self,
        ctx: AgentContext,
        text: str,
        state: ConversationCommerceState,
        decision: DecisionResult,
        slots: SlotResult,
    ) -> tuple[ReplyResult, list[dict[str, Any]]]:
        state.last_user_message = text
        action = decision.action_type
        logger.info(
            "订单动作开始：tenant=%s conversation=%s action=%s risk=%s draft=%s",
            ctx.tenant_id, ctx.conversation_id, action, decision.risk_level.value,
            state.draft_order_id or state.pending_order_id,
        )
        if action == ActionType.CREATE_DRAFT_ORDER:
            return await self._create_draft_order(ctx, text, state, decision, slots)
        if action == ActionType.UPDATE_QUANTITY:
            return await self._update_quantity(ctx, state, decision, slots)
        if action == ActionType.UPDATE_CONTACT:
            return await self._update_contact(ctx, state, decision, slots)
        if action == ActionType.CONFIRM_ORDER:
            return await self._confirm_order(ctx, state, decision)
        if action == ActionType.CANCEL_ORDER:
            return await self._cancel_order(ctx, state, decision)
        if action == ActionType.QUERY_ORDER:
            return await self._query_order(ctx, text, state, decision, slots)
        return ReplyResult(text="请告诉我要办理的订单事项。", response_type=ResponseType.FALLBACK), []

    async def _create_draft_order(
        self,
        ctx: AgentContext,
        text: str,
        state: ConversationCommerceState,
        decision: DecisionResult,
        slots: SlotResult,
    ) -> tuple[ReplyResult, list[dict[str, Any]]]:
        reference = await resolve_product_reference(
            text, state,
            global_search=lambda query: self._global_product_search(ctx, query),
        )
        if reference.ambiguous:
            logger.info("下单商品引用有歧义：tenant=%s conversation=%s candidates=%s",
                         ctx.tenant_id, ctx.conversation_id, len(reference.candidates))
            state.pending_candidates = reference.candidates
            state.last_recommended_products = reference.candidates
            return build_candidate_clarification_reply(reference.candidates), []

        product = reference.product or state.selected_product
        pending_candidates = state.pending_candidates or state.last_recommended_products
        if product is None and len(pending_candidates) == 1:
            product = dict(pending_candidates[0])
        if product is None:
            logger.info("下单缺少商品：tenant=%s conversation=%s", ctx.tenant_id, ctx.conversation_id)
            state.last_intent = ActionType.CREATE_DRAFT_ORDER
            state.last_agent_action = ActionType.CONSULT_PRODUCT
            state.last_skill = None
            state.stage = ConversationStage.PRODUCT_CANDIDATE_LISTED if pending_candidates else ConversationStage.PRODUCT_BROWSING
            return build_candidate_clarification_reply(pending_candidates), []

        quantity = slots.quantity or state.pending_quantity or 1
        address = slots.address or state.pending_address
        phone = slots.phone or state.pending_phone
        logger.info(
            "创建草稿订单：tenant=%s conversation=%s product=%s quantity=%s has_address=%s has_phone=%s",
            ctx.tenant_id,
            ctx.conversation_id,
            product.get("name"),
            quantity,
            bool(address),
            bool(phone),
        )
        state.selected_product = product
        if product.get("id") is not None:
            state.selected_product_id = str(product["id"])
            state.last_product_id = str(product["id"])

        result = await self.create_order_draft(
            tenant_id=ctx.tenant_id,
            contact_id=ctx.contact_id,
            db=ctx.db,
            conversation_id=ctx.conversation_id,
            items=[{"product_name": product["name"], "quantity": quantity}],
            shipping_address=address,
            receiver_phone=phone,
        )
        skill_result = _skill_result(result)
        tool_results = [_tool_dict(result)]
        if result.ok:
            payload = result.result if isinstance(result.result, dict) else {}
            order_id = str(payload.get("order_id") or "")
            state.pending_order_id = order_id
            state.draft_order_id = order_id
            state.missing_slots = [str(slot) for slot in payload.get("missing_info", [])]
            state.stage = ConversationStage.ORDER_PENDING_INFO if state.missing_slots else ConversationStage.ORDER_PENDING_CONFIRM
            state.pending_quantity = None
            state.pending_address = None
            state.pending_phone = None
        logger.info(
            "创建草稿订单完成：tenant=%s conversation=%s ok=%s draft=%s missing=%s",
            ctx.tenant_id,
            ctx.conversation_id,
            result.ok,
            _draft_order_id(state),
            state.missing_slots,
        )
        state.last_intent = ActionType.CREATE_DRAFT_ORDER
        state.last_skill = SkillName.CREATE_ORDER_DRAFT
        state.last_agent_action = SkillName.CREATE_ORDER_DRAFT
        return build_order_reply(skill_result, response_type=decision.response_type or ResponseType.DRAFT_ORDER_CREATED), tool_results

    async def _update_quantity(
        self,
        ctx: AgentContext,
        state: ConversationCommerceState,
        decision: DecisionResult,
        slots: SlotResult,
    ) -> tuple[ReplyResult, list[dict[str, Any]]]:
        order_id = _draft_order_id(state)
        if not order_id:
            if slots.quantity is not None:
                state.pending_quantity = slots.quantity
            logger.info(
                "无草稿订单，暂存数量：tenant=%s conversation=%s quantity=%s",
                ctx.tenant_id,
                ctx.conversation_id,
                slots.quantity,
            )
            return ReplyResult(text="数量我先记下了。请告诉我要下单的具体商品或服务。", response_type=ResponseType.MISSING_SLOTS), []
        logger.info(
            "修改草稿数量：tenant=%s conversation=%s draft=%s quantity=%s delta=%s",
            ctx.tenant_id,
            ctx.conversation_id,
            order_id,
            slots.quantity,
            slots.quantity_delta,
        )
        result = await self.update_draft_order_quantity(
            tenant_id=ctx.tenant_id,
            contact_id=ctx.contact_id,
            db=ctx.db,
            order_id=order_id,
            quantity=slots.quantity,
            quantity_delta=slots.quantity_delta,
        )
        if result.ok:
            payload = result.result if isinstance(result.result, dict) else {}
            state.missing_slots = [str(slot) for slot in payload.get("missing_info", state.missing_slots)]
            state.stage = ConversationStage.ORDER_PENDING_INFO if state.missing_slots else ConversationStage.ORDER_PENDING_CONFIRM
        state.last_intent = ActionType.UPDATE_QUANTITY
        state.last_skill = SkillName.UPDATE_DRAFT_ORDER_QUANTITY
        state.last_agent_action = SkillName.UPDATE_DRAFT_ORDER_QUANTITY
        logger.info(
            "修改草稿数量完成：tenant=%s conversation=%s ok=%s missing=%s",
            ctx.tenant_id,
            ctx.conversation_id,
            result.ok,
            state.missing_slots,
        )
        return build_order_reply(_skill_result(result), response_type=decision.response_type or ResponseType.DRAFT_ORDER_UPDATED), [_tool_dict(result)]

    async def _update_contact(
        self,
        ctx: AgentContext,
        state: ConversationCommerceState,
        decision: DecisionResult,
        slots: SlotResult,
    ) -> tuple[ReplyResult, list[dict[str, Any]]]:
        order_id = _draft_order_id(state)
        if not order_id:
            if slots.address:
                state.pending_address = slots.address
            if slots.phone:
                state.pending_phone = slots.phone
            state.last_intent = ActionType.UPDATE_CONTACT
            logger.info(
                "无草稿订单，暂存收货信息：tenant=%s conversation=%s has_address=%s has_phone=%s",
                ctx.tenant_id,
                ctx.conversation_id,
                bool(slots.address),
                bool(slots.phone),
            )
            return ReplyResult(text="收货信息我先记下了。您确认要下单的商品或服务后，我会带入订单草稿。", response_type=ResponseType.MISSING_SLOTS), []

        logger.info(
            "更新草稿收货信息：tenant=%s conversation=%s draft=%s has_address=%s has_phone=%s",
            ctx.tenant_id,
            ctx.conversation_id,
            order_id,
            bool(slots.address),
            bool(slots.phone),
        )
        result = await self.update_order_draft(
            tenant_id=ctx.tenant_id,
            contact_id=ctx.contact_id,
            db=ctx.db,
            order_id=order_id,
            shipping_address=slots.address,
            receiver_phone=slots.phone,
        )
        if result.ok:
            payload = result.result if isinstance(result.result, dict) else {}
            state.missing_slots = [str(slot) for slot in payload.get("missing_info", [])]
            state.stage = ConversationStage.ORDER_PENDING_INFO if state.missing_slots else ConversationStage.ORDER_PENDING_CONFIRM
        state.last_intent = ActionType.UPDATE_CONTACT
        state.last_skill = SkillName.UPDATE_ORDER_DRAFT
        state.last_agent_action = SkillName.UPDATE_ORDER_DRAFT
        logger.info(
            "更新草稿收货信息完成：tenant=%s conversation=%s ok=%s missing=%s",
            ctx.tenant_id, ctx.conversation_id, result.ok, state.missing_slots,
        )
        return build_order_reply(_skill_result(result), response_type=decision.response_type or ResponseType.DRAFT_ORDER_UPDATED), [_tool_dict(result)]

    async def _confirm_order(
        self,
        ctx: AgentContext,
        state: ConversationCommerceState,
        decision: DecisionResult,
    ) -> tuple[ReplyResult, list[dict[str, Any]]]:
        order_id = _draft_order_id(state)
        if not order_id:
            logger.info("确认订单失败，缺少草稿：tenant=%s conversation=%s", ctx.tenant_id, ctx.conversation_id)
            return ReplyResult(text="我还没有看到待确认的订单，请先选择商品或服务下单。", response_type=ResponseType.MISSING_SLOTS), []
        if decision.risk_level != RiskLevel.HIGH_RISK_WRITE:
            return ReplyResult(text="确认下单需要您明确回复「确认下单」。", response_type=ResponseType.MISSING_SLOTS), []

        logger.info("确认订单：tenant=%s conversation=%s draft=%s", ctx.tenant_id, ctx.conversation_id, order_id)
        result = await self.confirm_order(tenant_id=ctx.tenant_id, contact_id=ctx.contact_id, db=ctx.db, order_id=order_id)
        if result.ok:
            state.stage = ConversationStage.ORDER_CONFIRMED
            state.pending_order_id = None
            state.draft_order_id = None
            state.missing_slots = []
        state.last_intent = ActionType.CONFIRM_ORDER
        state.last_skill = SkillName.CONFIRM_ORDER
        state.last_agent_action = SkillName.CONFIRM_ORDER
        logger.info("确认订单完成：tenant=%s conversation=%s ok=%s", ctx.tenant_id, ctx.conversation_id, result.ok)
        return build_order_reply(_skill_result(result), response_type=decision.response_type or ResponseType.ORDER_CONFIRMED), [_tool_dict(result)]

    async def _cancel_order(
        self,
        ctx: AgentContext,
        state: ConversationCommerceState,
        decision: DecisionResult,
    ) -> tuple[ReplyResult, list[dict[str, Any]]]:
        order_id = _draft_order_id(state)
        if not order_id:
            state.last_intent = ActionType.CANCEL_ORDER
            logger.info("取消订单但无草稿：tenant=%s conversation=%s", ctx.tenant_id, ctx.conversation_id)
            return ReplyResult(text="当前没有待取消的订单。", response_type=ResponseType.ORDER_CANCELLED), []
        logger.info("取消订单：tenant=%s conversation=%s draft=%s", ctx.tenant_id, ctx.conversation_id, order_id)
        result = await self.cancel_order_draft(tenant_id=ctx.tenant_id, contact_id=ctx.contact_id, db=ctx.db, order_id=order_id)
        if result.ok:
            state.stage = ConversationStage.ORDER_CANCELLED
            state.pending_order_id = None
            state.draft_order_id = None
            state.missing_slots = []
        state.last_intent = ActionType.CANCEL_ORDER
        state.last_skill = SkillName.CANCEL_ORDER_DRAFT
        state.last_agent_action = SkillName.CANCEL_ORDER_DRAFT
        logger.info("取消订单完成：tenant=%s conversation=%s ok=%s", ctx.tenant_id, ctx.conversation_id, result.ok)
        return build_order_reply(_skill_result(result), response_type=decision.response_type or ResponseType.ORDER_CANCELLED), [_tool_dict(result)]

    async def _query_order(
        self,
        ctx: AgentContext,
        text: str,
        state: ConversationCommerceState,
        decision: DecisionResult,
        slots: SlotResult,
    ) -> tuple[ReplyResult, list[dict[str, Any]]]:
        if self.manage_order is None:
            return ReplyResult(text="订单查询能力暂不可用，请提供订单号后转人工确认。", response_type=ResponseType.FALLBACK), []
        logger.info(
            "查询订单：tenant=%s conversation=%s order_id=%s",
            ctx.tenant_id, ctx.conversation_id, slots.order_id,
        )
        result = await self.manage_order(
            tenant_id=ctx.tenant_id, contact_id=ctx.contact_id, db=ctx.db,
            order_id=slots.order_id, customer_text=text, **decision.skill_params,
        )
        state.last_intent = ActionType.QUERY_ORDER
        state.last_skill = SkillName.MANAGE_ORDER
        state.last_agent_action = SkillName.MANAGE_ORDER
        logger.info("查询订单完成：tenant=%s conversation=%s ok=%s", ctx.tenant_id, ctx.conversation_id, result.ok)
        return build_order_reply(_skill_result(result), response_type=decision.response_type or ResponseType.ORDER_QUERY_RESULT), [_tool_dict(result)]

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
        if match is None:
            return None
        return {
            "id": str(match.id),
            "name": match.name,
            "sku": match.sku,
            "price": float(match.price) if match.price else None,
            "stock": match.stock,
            "description": match.description or "",
        }

    async def _global_product_search(self, ctx: AgentContext, text: str) -> dict[str, Any] | None:
        if self.find_product_in_text is not None:
            return await self.find_product_in_text(ctx, text)
        return await self._find_product_in_text(ctx, text)


def _draft_order_id(state: ConversationCommerceState) -> str | None:
    return state.draft_order_id or state.pending_order_id


def _skill_result(result: ToolResult) -> SkillResult:
    return SkillResult(
        success=result.ok,
        skill_name=result.skill_name,
        data=result.result,
        error_message=result.error,
    )


def _tool_dict(result: ToolResult) -> dict[str, Any]:
    return {"skill_name": result.skill_name, "ok": result.ok, "result": result.result, "error": result.error}



