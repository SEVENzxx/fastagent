"""Agent generate_reply 系统提示词（支持租户自定义覆盖）。"""

from __future__ import annotations

from app.services.ai.tenant_ai_config import get_default_reply_system_prompt

GENERATE_REPLY_SYSTEM_PROMPT = get_default_reply_system_prompt()


def get_effective_system_prompt(tenant_custom_prompt: str | None = None) -> str:
    """返回有效的系统提示词：租户 custom_prompt 优先，否则使用平台默认值。"""
    if tenant_custom_prompt:
        return tenant_custom_prompt
    return GENERATE_REPLY_SYSTEM_PROMPT


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
