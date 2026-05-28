"""Agent generate_reply 系统提示词。"""

from __future__ import annotations

GENERATE_REPLY_SYSTEM_PROMPT = """\
你是企业微信客服助手，正在为客户提供售后服务。

请根据以下工具调用结果，用简洁、自然、礼貌的中文回复客户。
- 如果工具调用成功并返回了数据，请自然地组织成客户能理解的内容。
- 如果工具调用失败或返回空结果，请礼貌告知客户当前无法处理并建议下一步。
- 不要编造工具返回结果中没有的信息。
- 不要使用"根据工具调用结果"、"系统返回"、"查询结果显示"等透露内部机制的表述。
- 保持回复简洁，一次不要输出超过 200 字。
"""


def build_generate_reply_user_prompt(
    customer_text: str,
    tool_results: list[dict],
) -> str:
    """构造 generate_reply 用户提示词。"""
    results_text = _format_tool_results(tool_results)
    return (
        f"客户消息：{customer_text}\n\n"
        f"工具调用结果：\n{results_text}\n\n"
        f"请根据以上工具调用结果，生成自然回复。"
    )


def _format_tool_results(results: list[dict]) -> str:
    if not results:
        return "（无工具调用）"
    lines: list[str] = []
    for i, r in enumerate(results, 1):
        skill = r.get("skill_name", "unknown")
        ok = r.get("ok", False)
        if ok:
            result = r.get("result")
            lines.append(f"[{i}] {skill}: 成功 — {result}")
        else:
            error = r.get("error", "未知错误")
            lines.append(f"[{i}] {skill}: 失败 — {error}")
    return "\n".join(lines)
