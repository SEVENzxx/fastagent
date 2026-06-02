"""通用回复 Prompt。"""

from __future__ import annotations

from app.services.ai.types import Messages

CLARIFY_SYSTEM_PROMPT = (
    "你是智能客服助手。用户的意图不太明确，请先礼貌说明还需要更多信息，"
    "并引导用户具体描述需求。"
)
GENERAL_REPLY_SYSTEM_PROMPT = "你是智能客服助手。请根据用户内容自然回复，并引导用户提供更具体的业务需求。"
RAG_REPLY_SYSTEM_PROMPT = "你是智能客服助手。只依据以下知识库内容回复用户，用简洁自然的中文，不要编造信息。"


def build_clarify_messages(user_text: str) -> Messages:
    return _messages(CLARIFY_SYSTEM_PROMPT, user_text)


def build_general_reply_messages(user_text: str) -> Messages:
    return _messages(GENERAL_REPLY_SYSTEM_PROMPT, user_text)


def build_rag_reply_messages(user_text: str, knowledge_context: str) -> Messages:
    system_prompt = f"{RAG_REPLY_SYSTEM_PROMPT}\n\n知识库参考：\n{knowledge_context}"
    return _messages(system_prompt, user_text)


def _messages(system_prompt: str, user_text: str) -> Messages:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]
