"""商品知识问答 LLM prompt — Handler 不直接拼 prompt 字符串。"""

from __future__ import annotations

from typing import Any

from app.ai.types import Messages

SYSTEM_PROMPT = (
    "你是一个专业的电商客服。请根据提供的商品信息和知识库资料，"
    "简洁、准确地回答用户关于该商品的问题。"
    "回复保持友好、专业，不超过300字。"
)


def build_messages(
    question: str,
    product: dict[str, Any],
    knowledge: list[dict[str, Any]],
) -> Messages:
    """构建商品知识问答的 messages。"""
    name = product.get("name", "")
    desc = product.get("description", "") or ""
    features = "、".join(product.get("feature_tags") or [])
    chunks_text = "\n\n---\n".join(k.get("content", "") for k in knowledge[:3])

    user_prompt = (
        f"【商品名称】{name}\n"
        f"【商品描述】{desc}\n"
        f"【功能特点】{features or '无'}\n"
        f"\n【知识库资料】\n{chunks_text}\n"
        f"\n【用户问题】{question}\n"
        f"\n请根据以上信息回答用户问题。"
    )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
