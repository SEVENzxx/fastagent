"""基于本地小模型的电商路由决策 + 槽位提取。

替代 commerce_rules 的正则链，一次 LLM 调用同时完成路由分类和槽位提取，
通过语义理解判断用户意图和结构化信息，处理口语变体、歧义和否定表达。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.integrations.ollama_client import ollama_generate
from app.ai.schemas.commerce_types import CommerceRoute, DecisionResult, RiskLevel, SlotResult
from app.config import settings

logger = logging.getLogger(__name__)

_ROUTE_PROMPT = """你是电商客服路由分类器。判断用户意图并提取少量语义槽位。

输出严格JSON（不要markdown代码块）：
{{"route":"<ROUTE>","action_type":"<ACTION>","risk_level":"<RISK>","reason":"<简短理由>","address":null,"category":null,"confirm_flag":false,"cancel_flag":false}}

ROUTE（4选1）：
- PRODUCT_CONSULT：咨询商品、求推荐、比较、问价格库存参数、"有没有"、"看看"、"哪款好"、"适合什么人"、"好用吗"、"这款怎么样"
- ORDER_ACTION：明确下单/确认/取消/改数量/给地址电话/查订单
- FALLBACK：退出流程、"不看了"、"算了"
- GENERAL_RAG：闲聊问候、FAQ、开发票、发货、支付、其他非电商

关键判断：
- "想买...推荐"、"哪款好"、"适合什么人"、"好用吗" → PRODUCT_CONSULT
- "就买这个"、"确认下单"、"帮我下单"、"取消订单" → ORDER_ACTION
- "你好"、"谢谢"、"开发票" → GENERAL_RAG

语义槽位（正则已处理数量/序号/电话/订单号/商品关键词）：
- address：收货地址文本片段（如"北京市朝阳区XX路XX号"），没有填null
- category：商品分类名（如"户外摄像头"、"蓝牙耳机"），没有填null
- confirm_flag：用户明确确认操作（"确认"、"就这样"、"没问题"、"可以"→true）
- cancel_flag：用户明确取消操作（"取消"、"算了"、"不看了"、"不要了"→true）

状态：{context}
消息：{message}

输出JSON："""



async def route_commerce_message_llm(
    text: str,
    context: Any | None = None,
) -> tuple[DecisionResult, SlotResult] | None:
    """用本地小模型做路由决策+槽位提取。失败时返回 None，调用方降级到正则规则。"""

    context_summary = _build_context_summary(context)
    prompt = _ROUTE_PROMPT.format(context=context_summary, message=text.strip())

    try:
        raw = await ollama_generate(
            prompt,
            model=settings.AI_LOCAL_LLM_MODEL,
            base_url=settings.AI_LOCAL_LLM_BASE_URL,
            temperature=0.05,
            max_tokens=settings.AI_LOCAL_LLM_MAX_TOKENS,
            timeout=settings.AI_LOCAL_LLM_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.info("本地 LLM 路由调用失败，降级到规则路由：%s", exc)
        return None

    decision, slots = _parse_response(raw, text)
    if decision is None:
        return None

    logger.info(
        "LLM 路由命中：route=%s action=%s risk=%s reason=%s slots=%s",
        decision.route.value,
        decision.action_type,
        decision.risk_level.value,
        decision.reason,
        slots.model_dump(exclude_none=True),
    )
    return decision, slots


def _build_context_summary(context: Any | None) -> str:
    if context is None:
        return "无历史状态"

    parts: list[str] = []
    stage = getattr(context, "stage", None)
    if stage is not None:
        stage_val = stage.value if hasattr(stage, "value") else str(stage)
        parts.append(f"当前阶段={stage_val}")

    draft_id = getattr(context, "draft_order_id", None) or getattr(context, "pending_order_id", None)
    parts.append(f"有草稿订单={'是' if draft_id else '否'}")

    selected = getattr(context, "selected_product", None)
    if isinstance(selected, dict) and selected.get("name"):
        parts.append(f"已选商品={selected['name']}")

    # 最近讨论的商品关键词（即使没有精确选中商品，也能帮 LLM 理解上下文）
    last_keyword = getattr(context, "last_product_keyword", None)
    if last_keyword and (not isinstance(selected, dict) or not selected.get("name")):
        parts.append(f"最近商品={last_keyword}")

    # 候选商品数量
    candidates = getattr(context, "pending_candidates", None) or getattr(context, "last_displayed_candidates", None)
    if candidates:
        names = [
            str(item.get("name") or "")[:20]
            for item in (candidates if isinstance(candidates, list) else [])
            if isinstance(item, dict) and item.get("name")
        ][:3]
        if names:
            parts.append(f"候选商品={'/'.join(names)}")

    # 用户上一条消息（帮助 LLM 理解对话走向）
    last_msg = getattr(context, "last_user_message", None)
    if last_msg:
        parts.append(f"上条消息={str(last_msg)[:40]}")

    return "，".join(parts) if parts else "无历史状态"


_VALID_ROUTES = {r.value for r in CommerceRoute}
_RISK_MAP = {
    "product_consult": RiskLevel.READ_ONLY,
    "order_action": RiskLevel.LOW_RISK_WRITE,
    "confirm_order": RiskLevel.HIGH_RISK_WRITE,
    "cancel_order": RiskLevel.HIGH_RISK_WRITE,
}


def _parse_response(raw: str, text: str) -> tuple[DecisionResult, SlotResult] | tuple[None, None]:
    """从模型输出中同时提取路由决策和槽位。先尝试 JSON，失败则降级到纯文本路由名匹配。"""
    logger.info("LLM 路由原始输出：%s", raw[:250])

    data: dict[str, Any] | None = None

    # 1) 尝试 JSON 解析
    json_match = re.search(r"\{[^{}]*\}", raw)
    if json_match:
        try:
            data = json.loads(json_match.group(0))
        except json.JSONDecodeError:
            data = None

    if data is not None:
        decision = _decision_from_dict(data)
        if decision is not None:
            slots = _slots_from_dict(data, text)
            return decision, slots

    # 2) 降级：从纯文本中匹配路由名，槽位用正则兜底
    from app.ai.flows.commerce_rules import extract_slots

    upper = raw.upper()
    for route_name in ("PRODUCT_CONSULT", "ORDER_ACTION", "GENERAL_RAG", "FALLBACK"):
        if route_name in upper:
            route = CommerceRoute(route_name)
            decision = DecisionResult(
                route=route,
                action_type=_default_action(route),
                response_type=_default_response_type(route, _default_action(route)),
                risk_level=RiskLevel.READ_ONLY,
                reason="llm text matched",
            ) if route != CommerceRoute.GENERAL_RAG else DecisionResult(
                route=route, response_type="fallback",
                risk_level=RiskLevel.READ_ONLY, reason="llm text matched",
            )
            return decision, extract_slots(text)

    logger.info("LLM 路由输出无法解析：%s", raw[:100])
    return None, None


def _decision_from_dict(data: dict) -> DecisionResult | None:
    route_raw = str(data.get("route", "")).strip().upper()
    try:
        route = CommerceRoute(route_raw)
    except ValueError:
        logger.info("LLM 路由输出未知 route：%s", route_raw)
        return None

    action_type = data.get("action_type") or _default_action(route)
    risk_raw = str(data.get("risk_level", "READ_ONLY")).strip().upper()
    try:
        risk_level = RiskLevel(risk_raw)
    except ValueError:
        risk_level = _RISK_MAP.get((action_type or "").lower(), RiskLevel.READ_ONLY)

    reason = data.get("reason") or "llm classified"

    if route == CommerceRoute.GENERAL_RAG:
        return DecisionResult(route=route, response_type="fallback", risk_level=RiskLevel.READ_ONLY, reason=reason)

    return DecisionResult(
        route=route, action_type=action_type,
        response_type=_default_response_type(route, action_type),
        risk_level=risk_level, reason=reason,
    )


def _slots_from_dict(data: dict, text: str) -> SlotResult:
    """混合槽位提取：正则处理结构化字段，LLM 补全语义字段（地址/确认/取消/分类）。"""

    from app.ai.flows.commerce_rules import extract_slots

    regex_slots = extract_slots(text)

    # LLM 补全：地址（正则必须跟关键词如"地址""寄到"，LLM 可从自由文本中提取）
    llm_address = _safe_str(data.get("address"))
    if llm_address and not regex_slots.address:
        regex_slots.address = llm_address

    # LLM 补全：确认/取消意图
    if bool(data.get("confirm_flag")):
        regex_slots.confirm_flag = True
    if bool(data.get("cancel_flag")):
        regex_slots.cancel_flag = True

    # LLM 补全：分类名
    llm_category = _safe_str(data.get("category"))
    if llm_category and not regex_slots.category:
        regex_slots.category = llm_category

    return regex_slots


def _default_action(route: CommerceRoute) -> str | None:
    if route == CommerceRoute.PRODUCT_CONSULT:
        return "consult_product"
    if route == CommerceRoute.ORDER_ACTION:
        return None
    if route == CommerceRoute.FALLBACK:
        return "exit_flow"
    return None


def _default_response_type(route: CommerceRoute, action_type: str | None) -> str:
    if route == CommerceRoute.PRODUCT_CONSULT:
        return "product_knowledge_answer"
    if route == CommerceRoute.ORDER_ACTION:
        return "draft_order_created" if action_type == "create_draft_order" else "draft_order_updated"
    if route == CommerceRoute.FALLBACK:
        return "flow_exit"
    return "fallback"


def _safe_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    return str(value).strip() or None
