"""Agent 回复 Prompt 和固定兜底话术。"""

from __future__ import annotations

from app.ai.types import Messages

GENERATE_REPLY_SYSTEM_PROMPT = """\
你是智能客服助手，正在为客户提供服务。

请根据以下工具调用结果，用简洁、自然、礼貌的中文回复客户。
- 如果工具调用成功并返回了数据，请自然地组织成客户能理解的内容。
- 如果工具调用失败或返回空结果，请礼貌告知客户当前无法处理并建议下一步。
- 不要编造工具返回结果中没有的信息。
- 不要使用"根据工具调用结果"、"系统返回"、"查询结果显示"等透露内部机制的表述。
- 保持回复简洁，一次不要输出超过 200 字。
"""

CLARIFY_SYSTEM_PROMPT = (
    "你是智能客服助手。用户的意图不太明确，请用简洁礼貌的中文引导用户说明具体需求。"
    "不超过 60 字。"
)

FALLBACK_SYSTEM_PROMPT = "你是智能客服助手，请用简洁自然的中文回复用户，不超过 100 字。"

FALLBACK_MESSAGES = {
    "agent_planner": "抱歉，您的问题比较复杂，正在为您转接人工客服，请稍候。",
    "clarify_product_or_order": "请问您是想了解我们的产品，还是有具体的订单问题需要我帮您处理？",
    "generic_ack": "好的，我已收到您的消息。如需进一步帮助，请随时告诉我。",
    "empty_reply_general": "您好，请问有什么可以帮助您的？",
    "error_fallback": "抱歉，暂时无法处理您的请求，请稍后再试或转接人工客服。",
    "template_fallback": "好的，我已收到您的请求。",
}


def build_generate_reply_messages(
    customer_text: str,
    tool_results: list[dict],
    *,
    tenant_custom_prompt: str | None = None,
) -> Messages:
    """构造技能结果回复消息。"""
    results_text = _format_tool_results(tool_results)
    system_prompt = GENERATE_REPLY_SYSTEM_PROMPT
    if tenant_custom_prompt:
        system_prompt = f"{system_prompt}\n租户自定义人设：\n{tenant_custom_prompt.strip()}"
    user_prompt = (
        f"客户消息：{customer_text}\n\n"
        f"工具调用结果：\n{results_text}\n\n"
        "请根据以上工具调用结果，生成自然回复。"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def build_clarify_messages(customer_text: str) -> Messages:
    """构造 Agent 澄清追问消息。"""
    return _messages(CLARIFY_SYSTEM_PROMPT, customer_text or "用户暂未提供明确问题")


def build_fallback_messages(customer_text: str) -> Messages:
    """构造 Agent 无技能结果时的回复消息。"""
    return _messages(FALLBACK_SYSTEM_PROMPT, customer_text or "你好")


def _messages(system_prompt: str, user_text: str) -> Messages:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]


def _format_tool_results(results: list[dict]) -> str:
    if not results:
        return "（无工具调用）"
    lines: list[str] = []
    for index, item in enumerate(results, 1):
        skill = item.get("skill_name", "unknown")
        if item.get("ok", False):
            lines.append(f"[{index}] {skill}: 成功 - {item.get('result')}")
        else:
            lines.append(f"[{index}] {skill}: 失败 - {item.get('error', '未知错误')}")
    return "\n".join(lines)
