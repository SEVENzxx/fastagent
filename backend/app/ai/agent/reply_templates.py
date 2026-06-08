"""Deterministic customer-service reply templates."""

from __future__ import annotations

from typing import Any

from app.ai.agent.types import AgentState


FIXED_POLICY_REPLIES: dict[str, str] = {
    "delivery_time": "一般会按订单和库存情况尽快发货。您也可以提供具体商品或订单号，我帮您进一步确认发货时间。",
    "invoice": "可以为您处理发票相关需求。请提供订单号、发票类型和抬头信息，我帮您继续确认。",
    "payment_inquiry": "通常支持线上支付方式。具体可用方式会以订单结算页为准，您下单前也可以让我帮您确认。",
    "promotion_inquiry": "优惠活动会以当前店铺配置为准。您可以告诉我想了解的商品，我帮您查询是否有可用优惠。",
    "discount_request": "价格优惠需要结合商品和活动规则确认。您可以告诉我具体商品和数量，我帮您看是否有优惠空间。",
}


def fixed_policy_reply(intent: str | None) -> str | None:
    if not intent:
        return None
    return FIXED_POLICY_REPLIES.get(intent)


def render_agent_template_reply(state: AgentState) -> str | None:
    tool_results = list(state.get("tool_results") or [])
    if not tool_results:
        return None

    for renderer in (
        _missing_argument_reply,
        _argument_error_reply,
        lambda results: _human_approval_reply(state, results),
        lambda results: _confirmation_reply(state, results),
        _product_catalog_reply,
        _order_list_reply,
        _empty_result_reply,
        _tool_error_reply,
    ):
        reply = renderer(tool_results)
        if reply:
            return reply
    return None


def fallback_from_tool_results(tool_results: list[dict]) -> str:
    parts: list[str] = []
    for result in tool_results:
        if not result.get("ok"):
            continue
        payload = result.get("result")
        if isinstance(payload, dict) and payload.get("message"):
            parts.append(str(payload["message"]).strip())
        elif isinstance(payload, str):
            parts.append(payload.strip())
    return "\n\n".join(part for part in parts if part) or "好的，我已收到您的请求。"


def _missing_argument_reply(tool_results: list[dict]) -> str | None:
    prompts = [
        str(result.get("error") or "").strip()
        for result in tool_results
        if result.get("missing_arguments")
    ]
    prompts = [prompt for prompt in prompts if prompt]
    return "\n".join(dict.fromkeys(prompts)) if prompts else None


def _argument_error_reply(tool_results: list[dict]) -> str | None:
    has_error = any(
        (not result.get("ok")) and "参数校验失败" in str(result.get("error") or "")
        for result in tool_results
    )
    if not has_error:
        return None
    return "您提供的信息格式不太对，请换一种方式说明具体需求，我再帮您处理。"


def _human_approval_reply(state: AgentState, tool_results: list[dict]) -> str | None:
    plans = list(state.get("planned_tool_calls") or [])
    if not any(plan.get("risk_level") == "human_approval" for plan in plans):
        return None
    if any(result.get("ok") for result in tool_results):
        return "您的需求已记录，这类操作需要人工确认，我会为您转交客服处理。"
    return None


def _confirmation_reply(state: AgentState, tool_results: list[dict]) -> str | None:
    plans = list(state.get("planned_tool_calls") or [])
    write_confirm_skills = {
        str(plan.get("skill_name"))
        for plan in plans
        if plan.get("risk_level") == "write_confirm"
    }
    if not write_confirm_skills:
        return None

    messages: list[str] = []
    for result in tool_results:
        if not result.get("ok") or result.get("skill_name") not in write_confirm_skills:
            continue
        message = _payload_message(result.get("result"))
        if message:
            messages.append(message)
    return "\n\n".join(dict.fromkeys(messages)) if messages else None


def _empty_result_reply(tool_results: list[dict]) -> str | None:
    replies: list[str] = []
    for result in tool_results:
        if not result.get("ok"):
            continue
        payload = result.get("result")
        if not _is_empty_payload(payload):
            continue
        skill = str(result.get("skill_name") or "")
        replies.append(_payload_message(payload) or _empty_message_for_skill(skill))
    return "\n".join(dict.fromkeys(reply for reply in replies if reply)) if replies else None


def _product_catalog_reply(tool_results: list[dict]) -> str | None:
    replies: list[str] = []
    for result in tool_results:
        if not result.get("ok") or result.get("skill_name") != "search_products":
            continue
        payload = result.get("result")
        if not isinstance(payload, dict):
            continue
        result_type = str(payload.get("type") or "")
        if result_type == "category_suggestions":
            message = _payload_message(payload)
            if message:
                replies.append(message)
            continue
        products = payload.get("products")
        if isinstance(products, list) and products:
            replies.append(_render_product_list(products))
    return "\n\n".join(dict.fromkeys(replies)) if replies else None


def _order_list_reply(tool_results: list[dict]) -> str | None:
    replies: list[str] = []
    for result in tool_results:
        if not result.get("ok") or result.get("skill_name") != "manage_order":
            continue
        payload = result.get("result")
        if not isinstance(payload, dict):
            continue
        orders = payload.get("orders")
        if not isinstance(orders, list) or not orders:
            continue
        replies.append(_render_order_list(orders, int(payload.get("count") or len(orders))))
    return "\n\n".join(dict.fromkeys(replies)) if replies else None


def _tool_error_reply(tool_results: list[dict]) -> str | None:
    failed = [result for result in tool_results if not result.get("ok")]
    if not failed:
        return None
    if all(result.get("missing_arguments") for result in failed):
        return None
    return "暂时无法完成查询或操作，请稍后再试；如果比较着急，我可以帮您转人工处理。"


def _is_empty_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("count") == 0:
        return True
    for key in ("products", "orders", "items", "documents", "results"):
        if key in payload and payload.get(key) == []:
            return True
    return False


def _payload_message(payload: Any) -> str | None:
    if isinstance(payload, dict):
        message = str(payload.get("message") or "").strip()
        return message or None
    if isinstance(payload, str):
        return payload.strip() or None
    return None


def _empty_message_for_skill(skill: str) -> str:
    return {
        "search_products": "暂时没找到匹配的商品。您可以告诉我更具体的品类、品牌或型号，我再帮您查。",
        "manage_order": "暂时没有查到相关订单。您可以提供订单号或下单手机号，我再帮您确认。",
        "list_documents": "暂时没有找到匹配的资料。您可以换个关键词再试。",
    }.get(skill, "暂时没有查到匹配结果。您可以补充更具体的信息，我再帮您确认。")


def _render_product_list(products: list[dict]) -> str:
    lines = ["我帮您查到这些商品："]
    for product in products[:5]:
        name = str(product.get("name") or "").strip()
        if not name:
            continue
        price = product.get("price")
        stock = product.get("stock")
        desc = str(product.get("description") or "").strip()
        suffix: list[str] = []
        if price is not None:
            suffix.append(f"¥{float(price):.2f}")
        if stock is not None:
            suffix.append(f"库存 {stock}")
        line = f"- {name}"
        if suffix:
            line += f"（{'，'.join(suffix)}）"
        if desc:
            line += f"：{desc[:80]}"
        lines.append(line)
    lines.append("您想了解哪一款，或者需要我帮您下单哪一款？")
    return "\n".join(lines)


def _render_order_list(orders: list[dict], total: int) -> str:
    lines = [f"您共有 {total} 个订单，最近 {len(orders)} 个是："]
    for index, order in enumerate(orders[:5], start=1):
        order_id = str(order.get("order_id") or "").strip()
        status = str(order.get("status_label") or order.get("status") or "").strip()
        amount = float(order.get("payable_amount") or 0)
        lines.append(f"{index}. 订单 #{order_id}：{status}，应付 ¥{amount:.2f}")
        items = order.get("items")
        if isinstance(items, list):
            for item in items[:3]:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("product_name") or "商品").strip()
                quantity = item.get("quantity") or 1
                subtotal = float(item.get("subtotal") or 0)
                lines.append(f"   - {name} ×{quantity}，小计 ¥{subtotal:.2f}")
    lines.append("如果您想查看某一单的详细收货信息或物流，请把订单号发给我。")
    return "\n".join(lines)
