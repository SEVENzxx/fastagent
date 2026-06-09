"""确定性业务回复生成。"""

from __future__ import annotations

from typing import Any

from app.ai.schemas.commerce_types import ReplyResult, ResponseType, SkillResult

REPRESENTATIVE_PRODUCT_LIMIT = 3
FULL_PRODUCT_LIMIT = 5


def build_product_candidates_reply(products: list[dict[str, Any]], *, category: str | None = None) -> ReplyResult:
    if not products:
        text = (
            f"暂时没找到「{category}」相关商品或服务。您可以换个名称或补充需求，我再帮您查。"
            if category
            else "暂时没找到匹配的商品或服务。您可以补充具体名称、用途或需求，我再帮您查。"
        )
        return ReplyResult(
            text=text,
            response_type=ResponseType.PRODUCT_CANDIDATES,
        )
    if len(products) == 1:
        return build_product_detail_reply(products[0], response_type=ResponseType.PRODUCT_DETAIL)

    visible_limit = FULL_PRODUCT_LIMIT if len(products) <= FULL_PRODUCT_LIMIT else REPRESENTATIVE_PRODUCT_LIMIT
    lines = [f"我帮您找到这些{category}商品：" if category else "我帮您找到这些当前可选项："]
    for idx, product in enumerate(products[:visible_limit], start=1):
        suffix: list[str] = []
        if product.get("price") is not None:
            suffix.append(f"¥{float(product['price']):.2f}")
        if product.get("stock") is not None:
            suffix.append(f"库存 {product['stock']}")
        line = f"{idx}. {product.get('name')}"
        if suffix:
            line += f"（{'，'.join(suffix)}）"
        if product.get("description"):
            line += f"：{str(product['description'])[:80]}..."
        lines.append(line)
    if len(products) > FULL_PRODUCT_LIMIT:
        lines.append(f"这类商品还有 {len(products) - visible_limit} 款，我先展示上面 {visible_limit} 款代表款。")
        lines.append("您可以继续补充预算、用途、规格或想看的序号，我再帮您缩小范围。")
    else:
        lines.append("您想了解哪一款，或者需要我帮您下单哪一款？")
    return ReplyResult(text="\n".join(lines), response_type=ResponseType.PRODUCT_CANDIDATES)


def build_product_detail_reply(product: dict[str, Any], *, response_type: str = ResponseType.PRODUCT_DETAIL) -> ReplyResult:
    parts = [f"我帮您找到 1 款比较匹配的商品：{product.get('name')}"]
    details: list[str] = []
    if product.get("price") is not None:
        details.append(f"价格 ¥{float(product['price']):.2f}")
    if product.get("stock") is not None:
        details.append(f"库存 {product['stock']}")
    if details:
        parts.append("，".join(details))
    if product.get("description"):
        parts.append(str(product["description"]))
    parts.append("如果您觉得合适，可以回复「就买这款」或告诉我数量。")
    return ReplyResult(text="\n".join(parts), response_type=response_type)


def build_candidate_clarification_reply(candidates: list[dict[str, Any]]) -> ReplyResult:
    if candidates:
        lines = ["我找到几款可能相关的商品，请回复商品名或序号："]
        for idx, product in enumerate(candidates[:5], start=1):
            lines.append(f"{idx}. {product.get('name')}")
        return ReplyResult(text="\n".join(lines), response_type=ResponseType.CANDIDATE_CLARIFICATION)
    return ReplyResult(
        text="请告诉我要下单的具体商品或服务名称。也可以描述您的需求，我先帮您查相关选项。",
        response_type=ResponseType.CANDIDATE_CLARIFICATION,
    )


def build_order_reply(skill_result: SkillResult, *, response_type: str) -> ReplyResult:
    if not skill_result.success:
        return ReplyResult(
            text=skill_result.error_message or "业务处理失败，请稍后再试，或转人工确认。",
            response_type=ResponseType.FALLBACK,
        )
    payload = skill_result.data if isinstance(skill_result.data, dict) else {}
    message = str(payload.get("message") or "").strip()
    if response_type in {ResponseType.DRAFT_ORDER_CREATED, ResponseType.DRAFT_ORDER_UPDATED}:
        text = _render_order_next_step(payload, fallback=message or "订单草稿已更新。")
    elif response_type == ResponseType.ORDER_CONFIRMED:
        text = message or "订单已确认，后续由客服审核发货。"
    elif response_type == ResponseType.ORDER_CANCELLED:
        text = message or "已取消当前订单。"
    elif response_type == ResponseType.ORDER_QUERY_RESULT:
        text = message or _render_order_query(payload)
    else:
        text = message or "好的，我已处理。"
    return ReplyResult(text=text, response_type=response_type)


def build_missing_slots_reply(missing: list[str]) -> ReplyResult:
    return ReplyResult(text=missing_info_prompt(missing), response_type=ResponseType.MISSING_SLOTS)


def build_fallback_reply(*, product_category: str | None = None, purchase_intent: bool = False) -> ReplyResult:
    if product_category:
        text = "我先帮您看看相关商品，您可以选择一款继续了解。"
    elif purchase_intent:
        text = "请告诉我要下单的具体商品或服务名称。也可以描述您的需求，我先帮您查相关选项。"
    else:
        text = "这个问题我需要再确认一下。您也可以补充商品、订单号或想办理的事项。"
    return ReplyResult(text=text, response_type=ResponseType.FALLBACK)


def missing_info_prompt(missing: list[str]) -> str:
    labels = {"address": "收货地址", "phone": "联系电话"}
    needed = "、".join(labels.get(slot, slot) for slot in missing) or "收货信息"
    return f"还需要补充{needed}。"


def _render_order_next_step(payload: dict[str, Any], *, fallback: str) -> str:
    missing = [str(slot) for slot in payload.get("missing_info", [])]
    message = str(payload.get("message") or fallback).strip()
    if missing:
        return (message + "\n" if message else "") + missing_info_prompt(missing)
    return (message + "\n" if message else "") + "请确认以上订单信息，确认后回复「确认下单」。"


def _render_order_query(payload: dict[str, Any]) -> str:
    orders = payload.get("orders")
    if isinstance(orders, list):
        if not orders:
            return "暂时没有查到相关订单。您可以提供订单号或下单手机号，我再帮您确认。"
        lines = [f"我查到最近 {len(orders)} 个订单："]
        for idx, order in enumerate(orders[:5], start=1):
            lines.append(
                f"{idx}. 订单 #{order.get('order_id')}：{order.get('status_label') or order.get('status')}，"
                f"应付 ¥{float(order.get('payable_amount') or 0):.2f}"
            )
        return "\n".join(lines)
    if payload.get("order_id"):
        return (
            f"订单 #{payload.get('order_id')}：{payload.get('status_label') or payload.get('status')}，"
            f"应付 ¥{float(payload.get('payable_amount') or 0):.2f}"
        )
    return "暂时没有查到相关订单。您可以提供订单号或下单手机号，我再帮您确认。"
