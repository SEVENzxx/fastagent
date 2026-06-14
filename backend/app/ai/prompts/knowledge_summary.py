"""知识摘要 Prompt — 仅用于知识分块长内容的 LLM 摘要。

不要在此文件中混合其他用途的 Prompt。
"""

from __future__ import annotations

from app.ai.types import Messages

KNOWLEDGE_SUMMARY_SYSTEM = (
    "你是一个智能客服助手。请仅基于以下知识库内容回答用户问题，"
    "使用简洁自然的中文。不要编造信息。"
    "如果知识库内容不足以回答问题，请明确说明。"
)


def build_knowledge_summary_messages(
    user_text: str,
    knowledge_context: str,
) -> Messages:
    """构建知识摘要消息。

    参数：
        user_text: 用户原始问题。
        knowledge_context: 知识库参考内容。

    返回：
        Messages 列表，适用于 LLM stream / complete 调用。
    """
    system_prompt = f"{KNOWLEDGE_SUMMARY_SYSTEM}\n\n知识库参考：\n{knowledge_context}"
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]
