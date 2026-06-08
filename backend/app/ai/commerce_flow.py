"""确定性电商流程编排：商品咨询 → 下单 → 补信息 → 确认的全链路。

不经过 LangGraph Agent 的意图路由，直接在 router processor 中调用，
减少 LLM 调用次数，保证核心电商路径的响应速度和确定性。

整个流程基于阶段（ConversationStage）推进：
  IDLE → PRODUCT_BROWSING → PRODUCT_SELECTED → ORDER_DRAFTING
       → ORDER_PENDING_INFO → ORDER_PENDING_CONFIRM → IDLE
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from sqlalchemy import select

from app.ai.agent.types import AgentContext, ToolResult
from app.ai.memory.conversation_state import ConversationCommerceState, ConversationStage
from app.ai.skills.orders import (
    cancel_order_draft,
    confirm_order,
    create_order_draft,
    update_draft_order_quantity,
    update_order_draft,
)
from app.ai.skills.products import get_product_detail, list_product_categories, search_products
from app.models.category import Category
from app.models.product import Product

logger = logging.getLogger(__name__)

# ── 正则与语义常量 ──
PHONE_PATTERN = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")       # 手机号
ARABIC_QUANTITY_PATTERNS = (
    re.compile(r"(?:买|要|下单|来|订|拍|数量(?:改成|改为)?|改成)\s*(\d{1,2})\s*(?:件|个|台|部|盒|瓶|箱|包|袋|份|套)?"),
    re.compile(r"(\d{1,2})\s*(?:件|个|台|部|盒|瓶|箱|包|袋|份|套)"),
)
CHINESE_QUANTITIES = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
CHINESE_QUANTITY_PATTERN = re.compile(r"(?:买|要|下单|来|订|拍|数量(?:改成|改为)?|改成)?\s*(一|二|两|三|四|五|六|七|八|九|十)\s*(?:件|个|台|部|盒|瓶|箱|包|袋|份|套)?")

# 关键词匹配元组（按语义分组，便于后续扩展）
BUY_WORDS = ("我要买", "帮我下单", "买一个", "买一", "买个", "确认购买", "下单", "来一个", "订一个")
CONFIRM_WORDS = ("确认下单", "确认", "没问题", "可以", "就这样", "就这么定")
CANCEL_WORDS = ("取消", "取消订单", "不买了", "我不想买了", "不要了", "算了", "退出", "放弃", "先不买")
MODIFY_WORDS = ("改地址", "修改地址", "换地址", "改数量", "修改数量", "换成", "改成")
INCREMENT_QUANTITY_WORDS = ("再来", "再加", "多买", "加一个", "加一件", "加1个", "加1件")
DECREMENT_QUANTITY_WORDS = ("少一个", "少一件", "少1个", "少1件", "减一个", "减一件", "减1个", "减1件")
OVERVIEW_WORDS = ("公司有什么产品", "你们有什么产品", "有什么产品", "产品有哪些", "卖什么")
DETAIL_WORDS = ("怎么卖", "多少钱", "价格", "有货", "库存", "介绍一下")
ADDRESS_HINTS = ("地址", "收货", "寄到", "送到", "发到")
ADDRESS_KEYWORDS = ("省", "市", "区", "县", "镇", "乡", "街道", "路", "号", "小区", "单元", "楼", "室", "村", "组")
ORDINALS = {"第一个": 0, "第1个": 0, "1": 0, "第二个": 1, "第2个": 1, "2": 1, "第三个": 2, "第3个": 2, "3": 2}
ORDER_STAGES = {
    ConversationStage.ORDER_DRAFTING,
    ConversationStage.ORDER_PENDING_INFO,
    ConversationStage.ORDER_PENDING_CONFIRM,
}


@dataclass(slots=True)
class CommerceFlowResult:
    """电商流程执行结果：回复文本 + 更新后的状态 + 技能调用记录。"""
    text: str
    state: ConversationCommerceState
    tool_results: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class QuantityUpdateIntent:
    """草稿订单数量修改意图。quantity 是设置值，quantity_delta 是增减值。"""
    quantity: int | None = None
    quantity_delta: int | None = None


# ═══════════════════════════ 主入口 ═══════════════════════════

async def handle_commerce_flow(
    ctx: AgentContext,
    customer_text: str,
    state: ConversationCommerceState,
) -> CommerceFlowResult | None:
    """电商流程主入口，按阶段优先级依次判断。

    优先级顺序：
      1. 等待确认阶段 → 用户确认 → 提交订单
      2. 等待确认阶段 → 用户修改 → 更新订单
      3. 等待补信息阶段 → 填补收货信息
      4. 用户要求下单 → 创建订单
      5. 商品浏览/查询 → 展示/搜索商品

    返回 None 表示当前输入不属于电商流程，交给通用意图流水线处理。
    """
    text = customer_text.strip()
    if not text:
        return None

    logger.info(
        "[commerce] enter tenant=%s conversation=%s stage=%s pending_order=%s text=%s",
        ctx.tenant_id,
        ctx.conversation_id,
        state.stage.value,
        state.pending_order_id,
        text[:80],
    )

    # ── 优先级 1：已有订单草稿时，先处理取消/确认/补槽/修改，避免普通意图误抢。──
    if state.pending_order_id and state.stage in ORDER_STAGES:
        return await _handle_pending_order_message(ctx, text, state)

    # ── 优先级 4：用户要求下单 → 创建订单 ──
    if _is_create_order_intent(text):
        return await _handle_create_order(ctx, text, state)

    # ── 优先级 5：商品浏览/查询 → 分类展示或详情查询 ──
    product_intent = await _classify_product_query(ctx, text, state)
    if product_intent is None:
        return None
    intent, args = product_intent
    if intent == "product_overview":
        return await _handle_product_overview(ctx, text, state)
    if intent == "product_category_query":
        return await _handle_product_category(ctx, text, state, args["category"])
    return await _handle_product_detail(ctx, text, state, args["product_name"])


# ═══════════════════════════ 业务处理函数 ═══════════════════════════

async def _handle_product_overview(
    ctx: AgentContext,
    text: str,
    state: ConversationCommerceState,
) -> CommerceFlowResult:
    """展示全部商品分类（入口：用户问"你们卖什么"）。"""
    previous = state.stage
    result = await _call_tool("list_product_categories", list_product_categories, ctx)
    payload = result.result if isinstance(result.result, dict) else {}
    state.stage = ConversationStage.PRODUCT_BROWSING
    state.last_intent = "product_overview"
    state.last_recommended_products = []
    state.selected_product = None
    state.last_agent_action = "list_product_categories"
    _log_transition(ctx, previous, state)
    return CommerceFlowResult(_message_from_result(result), state, [_tool_dict(result)])


async def _handle_product_category(
    ctx: AgentContext,
    text: str,
    state: ConversationCommerceState,
    category: str,
) -> CommerceFlowResult:
    """按分类搜索商品（入口：用户问"有没有茶叶/平板电脑"）。"""
    previous = state.stage
    result = await _call_tool("search_products", search_products, ctx, category=category, query=category)
    products = _products_from_result(result)
    state.stage = ConversationStage.PRODUCT_BROWSING
    state.last_intent = "product_category_query"
    state.last_recommended_products = products
    state.selected_product = products[0] if len(products) == 1 else None
    state.last_agent_action = "search_products"
    _log_transition(ctx, previous, state)
    return CommerceFlowResult(_render_products(products, category=category), state, [_tool_dict(result)])


async def _handle_product_detail(
    ctx: AgentContext,
    text: str,
    state: ConversationCommerceState,
    product_name: str,
) -> CommerceFlowResult:
    """查询商品详情（入口：用户问"乌苏啤酒多少钱"）。"""
    previous = state.stage
    result = await _call_tool("get_product_detail", get_product_detail, ctx, product_name=product_name, query=text)
    products = _products_from_result(result)
    state.last_intent = "product_detail_query"
    state.last_recommended_products = products
    state.selected_product = products[0] if len(products) == 1 else None
    state.stage = ConversationStage.PRODUCT_SELECTED if state.selected_product else ConversationStage.PRODUCT_BROWSING
    state.last_agent_action = "get_product_detail"
    _log_transition(ctx, previous, state)
    return CommerceFlowResult(_message_from_result(result), state, [_tool_dict(result)])


async def _handle_create_order(
    ctx: AgentContext,
    text: str,
    state: ConversationCommerceState,
) -> CommerceFlowResult:
    """创建订单草稿（入口：用户说"帮我下单两瓶乌苏啤酒"）。

    先解析要买什么商品（从上下文或文本中提取），
    再提取收货信息，最后调用 create_order_draft 创建草稿。
    缺信息时进入 ORDER_PENDING_INFO 等待用户补充。
    """
    previous = state.stage
    product = await _resolve_purchase_product(ctx, text, state)
    if product is None:
        # 用户在上一轮浏览了商品但没有选定，让他选
        state.stage = ConversationStage.PRODUCT_BROWSING
        state.last_intent = "create_order_intent"
        state.last_agent_action = "ask_product_selection"
        _log_transition(ctx, previous, state)
        return CommerceFlowResult(_ask_product_selection(state), state, [])

    quantity = _extract_quantity(text) or 1
    slots = _extract_order_slots(text)
    state.stage = ConversationStage.ORDER_DRAFTING
    state.last_intent = "create_order_intent"
    state.selected_product = product
    state.last_agent_action = "create_order_draft"
    _log_transition(ctx, previous, state)

    result = await _call_tool(
        "create_order_draft",
        create_order_draft,
        ctx,
        conversation_id=ctx.conversation_id,
        items=[{"product_name": product["name"], "quantity": quantity}],
        shipping_address=slots.get("shipping_address"),
        receiver_phone=slots.get("receiver_phone"),
        receiver_name=slots.get("receiver_name"),
    )
    if not result.ok:
        state.stage = ConversationStage.PRODUCT_BROWSING
        state.missing_slots = ["product"]
        return CommerceFlowResult(_message_from_result(result), state, [_tool_dict(result)])

    payload = result.result if isinstance(result.result, dict) else {}
    state.pending_order_id = str(payload.get("order_id") or "")
    state.missing_slots = [str(slot) for slot in payload.get("missing_info", [])]
    state.stage = ConversationStage.ORDER_PENDING_INFO if state.missing_slots else ConversationStage.ORDER_PENDING_CONFIRM
    state.last_agent_action = "ask_order_info" if state.missing_slots else "ask_order_confirm"
    _log_transition(ctx, ConversationStage.ORDER_DRAFTING, state)
    return CommerceFlowResult(_render_order_next_step(payload), state, [_tool_dict(result)])


async def _handle_pending_order_message(
    ctx: AgentContext,
    text: str,
    state: ConversationCommerceState,
) -> CommerceFlowResult:
    """处理已有订单草稿后的后续消息：取消、补信息、修改或确认。"""
    previous = state.stage
    quantity_update = _extract_quantity_update_intent(text)

    logger.info(
        "[commerce] pending_order_action tenant=%s conversation=%s order_id=%s stage=%s action=%s quantity=%s quantity_delta=%s",
        ctx.tenant_id,
        ctx.conversation_id,
        state.pending_order_id,
        state.stage.value,
        "cancel" if _contains_any(text, CANCEL_WORDS) else "quantity_update" if quantity_update else "pending_info_or_confirm",
        quantity_update.quantity if quantity_update else None,
        quantity_update.quantity_delta if quantity_update else None,
    )

    if _contains_any(text, CANCEL_WORDS):
        return await _handle_order_cancel(ctx, text, state)

    if quantity_update is not None:
        return await _handle_order_quantity_update(ctx, text, state, quantity_update)

    if state.stage == ConversationStage.ORDER_PENDING_CONFIRM:
        if _contains_any(text, CONFIRM_WORDS):
            return await _handle_order_confirm(ctx, text, state)
        if _contains_any(text, MODIFY_WORDS) or _has_order_update_content(text):
            return await _handle_order_update(ctx, text, state, require_slot=False)

        state.last_intent = "order_confirm_pending"
        state.last_agent_action = "ask_order_confirm"
        _log_transition(ctx, previous, state)
        return CommerceFlowResult(
            "请确认是否提交当前订单。确认请回复「确认下单」，需要调整请告诉我要修改的内容。",
            state,
            [],
        )

    if state.stage == ConversationStage.ORDER_PENDING_INFO:
        if _contains_any(text, CONFIRM_WORDS):
            state.last_intent = "confirm_order_missing_info"
            state.last_agent_action = "ask_order_info"
            _log_transition(ctx, previous, state)
            return CommerceFlowResult(_missing_info_prompt(state.missing_slots), state, [])
        return await _handle_order_update(ctx, text, state, require_slot=True)

    if _contains_any(text, CONFIRM_WORDS):
        return await _handle_order_confirm(ctx, text, state)
    return await _handle_order_update(ctx, text, state, require_slot=True)


async def _handle_order_quantity_update(
    ctx: AgentContext,
    text: str,
    state: ConversationCommerceState,
    quantity_update: QuantityUpdateIntent,
) -> CommerceFlowResult:
    """更新当前草稿订单的商品数量，不受地址/电话缺失影响。"""
    _ = text
    previous = state.stage
    if not state.pending_order_id:
        return CommerceFlowResult("请先确认要修改的订单。", state, [])

    result = await _call_tool(
        "update_draft_order_quantity",
        update_draft_order_quantity,
        ctx,
        order_id=state.pending_order_id,
        quantity=quantity_update.quantity,
        quantity_delta=quantity_update.quantity_delta,
    )
    payload = result.result if isinstance(result.result, dict) else {}
    state.last_intent = "order_quantity_update"
    state.missing_slots = [str(slot) for slot in payload.get("missing_info", state.missing_slots)]
    state.stage = ConversationStage.ORDER_PENDING_INFO if state.missing_slots else ConversationStage.ORDER_PENDING_CONFIRM
    state.last_agent_action = "update_draft_order_quantity"
    _log_transition(ctx, previous, state)
    return CommerceFlowResult(_render_order_next_step(payload), state, [_tool_dict(result)])


async def _handle_order_update(
    ctx: AgentContext,
    text: str,
    state: ConversationCommerceState,
    *,
    require_slot: bool,
) -> CommerceFlowResult:
    """更新订单草稿（补收货信息、改数量、换商品）。"""
    previous = state.stage
    if not state.pending_order_id:
        return CommerceFlowResult("请先确认要修改的订单。", state, [])

    slots = _extract_order_slots(text)
    quantity = _extract_quantity(text) if "数量" in text or "改数量" in text else None
    product_name = await _extract_replacement_product(ctx, text) if "换成" in text or "改成" in text else None
    if require_slot and not slots and quantity is None and product_name is None:
        state.stage = ConversationStage.ORDER_PENDING_INFO
        state.last_agent_action = "ask_order_info"
        _log_transition(ctx, previous, state)
        return CommerceFlowResult(_missing_info_prompt(state.missing_slots), state, [])

    result = await _call_tool(
        "update_order_draft",
        update_order_draft,
        ctx,
        order_id=state.pending_order_id,
        shipping_address=slots.get("shipping_address"),
        receiver_phone=slots.get("receiver_phone"),
        receiver_name=slots.get("receiver_name"),
        quantity=quantity,
        product_name=product_name,
    )
    payload = result.result if isinstance(result.result, dict) else {}
    state.last_intent = "order_info_update"
    state.missing_slots = [str(slot) for slot in payload.get("missing_info", [])]
    state.stage = ConversationStage.ORDER_PENDING_INFO if state.missing_slots else ConversationStage.ORDER_PENDING_CONFIRM
    state.last_agent_action = "ask_order_info" if state.missing_slots else "ask_order_confirm"
    _log_transition(ctx, previous, state)
    return CommerceFlowResult(_render_order_next_step(payload), state, [_tool_dict(result)])


async def _handle_order_cancel(
    ctx: AgentContext,
    text: str,
    state: ConversationCommerceState,
) -> CommerceFlowResult:
    """取消当前订单草稿，并清理会话中的待确认订单状态。"""
    _ = text
    previous = state.stage
    if not state.pending_order_id:
        state.stage = ConversationStage.IDLE
        state.last_intent = "cancel_order"
        state.last_agent_action = "cancel_order_missing_order"
        _log_transition(ctx, previous, state)
        return CommerceFlowResult("当前没有待取消的订单。", state, [])

    result = await _call_tool("cancel_order_draft", cancel_order_draft, ctx, order_id=state.pending_order_id)
    state.last_intent = "cancel_order"
    state.last_agent_action = "cancel_order_draft"
    if result.ok:
        state.stage = ConversationStage.IDLE
        state.pending_order_id = None
        state.missing_slots = []
        state.selected_product = None
    _log_transition(ctx, previous, state)
    return CommerceFlowResult(_message_from_result(result), state, [_tool_dict(result)])


async def _handle_order_confirm(
    ctx: AgentContext,
    text: str,
    state: ConversationCommerceState,
) -> CommerceFlowResult:
    """确认订单：调用 confirm_order 正式提交。

    确认成功后重置会话状态（stage → IDLE），清除所有临时数据。
    """
    previous = state.stage
    if not state.pending_order_id:
        state.stage = ConversationStage.IDLE
        state.last_agent_action = "confirm_order_missing_order"
        _log_transition(ctx, previous, state)
        return CommerceFlowResult("我还没有看到待确认的订单，请先选择商品下单。", state, [])

    result = await _call_tool("confirm_order", confirm_order, ctx, order_id=state.pending_order_id)
    state.last_intent = "confirm_order"
    state.last_agent_action = "confirm_order"
    if result.ok:
        # 下单成功，清空会话状态回到初始
        state.stage = ConversationStage.IDLE
        state.pending_order_id = None
        state.missing_slots = []
        state.selected_product = None
        state.last_recommended_products = []
    _log_transition(ctx, previous, state)
    return CommerceFlowResult(_message_from_result(result), state, [_tool_dict(result)])


# ═══════════════════════════ 意图分类 ═══════════════════════════

async def _classify_product_query(
    ctx: AgentContext,
    text: str,
    state: ConversationCommerceState,
) -> tuple[str, dict[str, str]] | None:
    """判断用户输入的商品查询意图：总览 / 分类搜索 / 详情查询。

    规则引擎（无 LLM）：
      - 包含"有什么/卖什么" → 总览
      - 包含分类名 + "有什么" → 分类搜索
      - 包含"多少钱/价格/库存" → 商品详情
    """
    if _contains_any(text, OVERVIEW_WORDS):
        return "product_overview", {}
    category = await _category_from_text(ctx, text)
    if category and ("有什么" in text or "推荐" in text or "看看" in text):
        return "product_category_query", {"category": category}
    if _contains_any(text, DETAIL_WORDS):
        product_name = _strip_product_question(text)
        if not product_name and state.selected_product:
            product_name = str(state.selected_product.get("name") or "")
        if product_name:
            return "product_detail_query", {"product_name": product_name}
    return None


async def _category_from_text(ctx: AgentContext, text: str) -> str | None:
    """从数据库中已有的分类名匹配用户输入。

    优先匹配最长的分类名（避免"茶"匹配到"茶叶"之前先匹配更精确的）。
    如果数据库无匹配，尝试硬编码常用品类（平板/电脑/手机）。
    """
    result = await ctx.db.execute(select(Category.name).where(Category.tenant_id == ctx.tenant_id))
    names = [str(name) for name in result.scalars().all() if name]
    # 长名优先（"平板电脑" 优先于 "电脑"）
    match = next((name for name in sorted(names, key=len, reverse=True) if name in text), None)
    if match:
        return match
    for candidate in ("平板电脑", "平板", "电脑", "手机"):
        if candidate in text:
            return candidate
    return None


# ═══════════════════════════ 商品解析 ═══════════════════════════

async def _resolve_purchase_product(
    ctx: AgentContext,
    text: str,
    state: ConversationCommerceState,
) -> dict[str, Any] | None:
    """确定用户要买哪个商品（多级回退）。

    来源优先级：
      1. 序号选择："第一个"、"1"
      2. 商品名匹配：文本中包含已推荐商品的名字
      3. 已选商品：上一轮选定过
      4. 唯一推荐：上一轮只推荐了一个
      5. 全文搜索：在数据库中按商品名匹配
    """
    ordinal = _ordinal_from_text(text)
    if ordinal is not None and 0 <= ordinal < len(state.last_recommended_products):
        return state.last_recommended_products[ordinal]

    for product in state.last_recommended_products:
        name = str(product.get("name") or "")
        if name and name in text:
            return product

    if state.selected_product is not None:
        return state.selected_product

    if len(state.last_recommended_products) == 1:
        return state.last_recommended_products[0]

    if _has_possible_product_text(text):
        explicit = await _find_product_in_text(ctx, text)
        if explicit is not None:
            return explicit
    return None


async def _find_product_in_text(ctx: AgentContext, text: str) -> dict[str, Any] | None:
    """在租户商品库中模糊匹配用户输入的商品名。"""
    result = await ctx.db.execute(
        select(Product)
        .where(Product.tenant_id == ctx.tenant_id, Product.is_active.is_(True))
        .order_by(Product.updated_at.desc(), Product.created_at.desc())
        .limit(100)
    )
    products = list(result.scalars().all())
    # 长名优先匹配（"乌龙茶" 优先于 "茶"）
    match = next(
        (product for product in sorted(products, key=lambda p: len(p.name or ""), reverse=True)
         if product.name and product.name in text),
        None,
    )
    if match is None:
        return None
    return _product_payload(match)


async def _extract_replacement_product(ctx: AgentContext, text: str) -> str | None:
    """提取用户要换成的商品名。"""
    product = await _find_product_in_text(ctx, text)
    return str(product["name"]) if product else None


# ═══════════════════════════ 字段抽取 ═══════════════════════════

def _extract_order_slots(text: str) -> dict[str, str]:
    """从文本中提取收货信息：手机号、地址。"""
    slots: dict[str, str] = {}
    phone = PHONE_PATTERN.search(text)
    if phone:
        slots["receiver_phone"] = phone.group(1)
    address = _extract_address(text)
    if address:
        slots["shipping_address"] = address
    return slots


def _extract_address(text: str) -> str | None:
    """从文本中截取收货地址（地址提示词后的部分，去除非地址成分）。"""
    for hint in ADDRESS_HINTS:
        if hint not in text:
            continue
        tail = text.split(hint, 1)[1].strip(" :：，,。")
        if not tail:
            continue
        # 去掉地址后面的电话/联系方式
        tail = re.split(r"(?:电话|手机号|手机|联系方式|联系)", tail, maxsplit=1)[0].strip(" :：，,。")
        phone = PHONE_PATTERN.search(tail)
        if phone:
            tail = tail.replace(phone.group(1), "").strip(" :：，,。")
        return tail or None
    return None


def _extract_quantity(text: str) -> int | None:
    """提取商品数量（支持中文数字和阿拉伯数字）。"""
    for char, value in CHINESE_QUANTITIES.items():
        if f"{char}个" in text or f"{char}台" in text or f"{char}部" in text or f"{char}件" in text:
            return value
    for pattern in ARABIC_QUANTITY_PATTERNS:
        match = pattern.search(text)
        if match:
            return max(int(match.group(1)), 1)
    chinese_match = CHINESE_QUANTITY_PATTERN.search(text)
    if chinese_match:
        return CHINESE_QUANTITIES.get(chinese_match.group(1))
    return None


def _extract_quantity_update_intent(text: str) -> QuantityUpdateIntent | None:
    """识别草稿订单数量修改：设置为固定数量，或在当前数量上增减。"""
    quantity = _extract_quantity(text)
    if _contains_any(text, INCREMENT_QUANTITY_WORDS):
        return QuantityUpdateIntent(quantity_delta=quantity or 1)
    if _contains_any(text, DECREMENT_QUANTITY_WORDS):
        return QuantityUpdateIntent(quantity_delta=-(quantity or 1))
    if quantity is not None and _looks_like_quantity_update(text):
        return QuantityUpdateIntent(quantity=quantity)
    return None


# ═══════════════════════════ 判断辅助 ═══════════════════════════

def _is_create_order_intent(text: str) -> bool:
    """判断是否是下单意图。"""
    return _contains_any(text, BUY_WORDS)


def _has_possible_product_text(text: str) -> bool:
    """去掉下单/确认等词后，是否仍有文本残留（可能是商品名）。"""
    cleaned = text
    for word in BUY_WORDS:
        cleaned = cleaned.replace(word, "")
    for word in ("我要", "帮我", "一个", "一下", "吧", "呀", "呢", "确认购买"):
        cleaned = cleaned.replace(word, "")
    return bool(cleaned.strip(" :：，,。！!"))


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    """检查文本是否包含任意一个关键词。"""
    return any(word in text for word in words)


def _has_order_update_content(text: str) -> bool:
    """判断文本是否包含可用于更新订单草稿的信息。"""
    return bool(_extract_order_slots(text) or _extract_quantity(text) is not None)


def _looks_like_quantity_update(text: str) -> bool:
    """判断带数量的短句是否是在修改当前草稿数量。"""
    quantity_words = ("数量", "改成", "改为", "要", "买", "来", "订", "拍")
    units = ("个", "件", "台", "部", "盒", "瓶", "箱", "包", "袋", "份", "套")
    if any(word in text for word in quantity_words):
        return True
    if any(unit in text for unit in units):
        return True
    # “两个摄像头”这类表达可能只有量词 + 商品名，进入草稿态时优先视为修改数量。
    return any(f"{char}个" in text or f"{char}件" in text for char in CHINESE_QUANTITIES)


def _ordinal_from_text(text: str) -> int | None:
    """提取序号：用户说"第一个"、"第2个"、"3" 等。"""
    for token, idx in ORDINALS.items():
        if token in text:
            return idx
    return None


def _strip_product_question(text: str) -> str:
    """去掉商品查询中的辅助词，提取商品名。"""
    cleaned = text
    for word in DETAIL_WORDS + ("这个", "这款", "吗", "？", "?", "呢"):
        cleaned = cleaned.replace(word, "")
    return cleaned.strip(" :：，,。！!")


# ═══════════════════════════ 数据转换 ═══════════════════════════

def _products_from_result(result: ToolResult) -> list[dict[str, Any]]:
    """从技能结果中提取商品列表。"""
    payload = result.result if isinstance(result.result, dict) else {}
    if isinstance(payload.get("products"), list):
        return [dict(item) for item in payload["products"] if isinstance(item, dict)]
    if isinstance(payload.get("product"), dict):
        return [dict(payload["product"])]
    return []


def _product_payload(product: Product) -> dict[str, Any]:
    """将 ORM Product 对象转为纯字典。"""
    return {
        "id": str(product.id),
        "name": product.name,
        "price": float(product.price) if product.price else None,
        "stock": product.stock,
        "description": product.description or "",
    }


# ═══════════════════════════ 工具调用与日志 ═══════════════════════════

async def _call_tool(
    name: str,
    func: Callable[..., Awaitable[ToolResult]],
    ctx: AgentContext,
    **kwargs: Any,
) -> ToolResult:
    """调用一个 Agent 技能并记录日志。"""
    logger.info(
        "[commerce] tool_call name=%s tenant=%s conversation=%s args=%s",
        name,
        ctx.tenant_id,
        ctx.conversation_id,
        _safe_tool_args(kwargs),
    )
    result = await func(tenant_id=ctx.tenant_id, contact_id=ctx.contact_id, db=ctx.db, **kwargs)
    logger.info("[commerce] tool_result name=%s ok=%s error=%s", name, result.ok, result.error)
    return result


def _log_transition(
    ctx: AgentContext,
    previous: ConversationStage,
    state: ConversationCommerceState,
) -> None:
    """记录会话阶段迁移。"""
    logger.info(
        "[commerce] state_transition tenant=%s conversation=%s %s -> %s intent=%s action=%s pending_order=%s missing=%s",
        ctx.tenant_id,
        ctx.conversation_id,
        previous.value,
        state.stage.value,
        state.last_intent,
        state.last_agent_action,
        state.pending_order_id,
        state.missing_slots,
    )


def _tool_dict(result: ToolResult) -> dict[str, Any]:
    """将 ToolResult 转为结构化字典。"""
    return {"skill_name": result.skill_name, "ok": result.ok, "result": result.result, "error": result.error}


def _safe_tool_args(kwargs: dict[str, Any]) -> dict[str, Any]:
    """日志参数脱敏：不记录完整手机号、地址、收货人。"""
    safe = dict(kwargs)
    if safe.get("receiver_phone"):
        phone = str(safe["receiver_phone"])
        safe["receiver_phone"] = phone[:3] + "****" + phone[-4:] if len(phone) >= 7 else "***"
    if safe.get("shipping_address"):
        safe["shipping_address"] = "<redacted>"
    if safe.get("receiver_name"):
        safe["receiver_name"] = "<redacted>"
    return safe


# ═══════════════════════════ 回复模板 ═══════════════════════════

def _message_from_result(result: ToolResult) -> str:
    """从技能结果中提取用户可见的回复文本。"""
    if isinstance(result.result, dict) and result.result.get("message"):
        return str(result.result["message"])
    if isinstance(result.result, str):
        return result.result
    return result.error or "好的，我已处理。"


def _render_products(products: list[dict[str, Any]], *, category: str) -> str:
    """格式化商品列表回复。"""
    if not products:
        return f"暂时没找到「{category}」相关商品。您可以换个品类或型号，我再帮您查。"
    lines = [f"我帮您找到这些{category}商品："]
    for idx, product in enumerate(products[:5], start=1):
        suffix: list[str] = []
        if product.get("price") is not None:
            suffix.append(f"¥{float(product['price']):.2f}")
        if product.get("stock") is not None:
            suffix.append(f"库存 {product['stock']}")
        line = f"{idx}. {product.get('name')}"
        if suffix:
            line += f"（{'，'.join(suffix)}）"
        if product.get("description"):
            line += f"：{str(product['description'])[:80]}"
        lines.append(line)
    lines.append("您想了解哪一款，或者需要我帮您下单哪一款？")
    return "\n".join(lines)


def _ask_product_selection(state: ConversationCommerceState) -> str:
    """用户要下单但没指定商品 → 让用户选。"""
    if state.last_recommended_products:
        lines = ["您想买哪一款？请回复商品名或序号："]
        for idx, product in enumerate(state.last_recommended_products[:5], start=1):
            lines.append(f"{idx}. {product.get('name')}")
        return "\n".join(lines)
    return "请告诉我要下单的具体商品名称和数量。"


def _render_order_next_step(payload: dict[str, Any]) -> str:
    """渲染订单草稿后的下一步提示（缺信息 → 补填；全了 → 确认）。"""
    if not payload:
        return "订单信息更新失败，请稍后再试。"
    message = str(payload.get("message") or "").strip()
    missing = [str(slot) for slot in payload.get("missing_info", [])]
    if missing:
        return (message + "\n" if message else "") + _missing_info_prompt(missing)
    return (message + "\n" if message else "") + "请确认以上订单信息，确认后回复「确认下单」。"


def _missing_info_prompt(missing: list[str]) -> str:
    """生成缺参追问话术。"""
    labels = {"address": "收货地址", "phone": "联系电话"}
    needed = "、".join(labels.get(slot, slot) for slot in missing) or "收货信息"
    return f"还需要补充{needed}。"
