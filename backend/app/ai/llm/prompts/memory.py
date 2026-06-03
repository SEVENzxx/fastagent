"""客户记忆提取 Prompt。"""

from __future__ import annotations

from app.ai.types import Messages

MEMORY_EXTRACT_SYSTEM_PROMPT = """\
你从客户消息中提取值得记住的偏好或信息。输出 JSON：
{"items": [{"key": "偏好维度", "value": "偏好值"}, ...], "nothing": false}
规则：key 是简洁标签如 "favorite_flavor"；value 是客户表达的具体偏好；
无可记忆信息输出 {"items": [], "nothing": true}；不编造、不输出 Markdown。"""


def build_memory_extract_messages(customer_text: str) -> Messages:
    return [
        {"role": "system", "content": MEMORY_EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": customer_text},
    ]
