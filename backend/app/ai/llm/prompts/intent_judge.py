"""LLMIntentJudge Prompt。"""

from __future__ import annotations

from app.ai.classifier.types import IntentCandidate
from app.ai.types import Messages


INTENT_JUDGE_SYSTEM_PROMPT = """你是智能客服意图精判器。
只能从候选意图中选择 primary_intent 和 secondary_intents，不能发明新的 intent。
必须输出 JSON：
{"primary_intent":"...","secondary_intents":[],"need_clarification":false,"reason":"..."}
不要输出 Markdown 或额外解释。"""


def build_intent_judge_user_prompt(text: str, candidates: list[IntentCandidate]) -> str:
    """把用户消息和候选意图组装为 LLM 输入。"""
    candidate_lines = "\n".join(
        f"- intent={item.intent}, label={item.label}, score={item.score:.2f}, reason={item.reason or ''}"
        for item in candidates
    )
    return f"""用户消息:
{text}

候选意图:
{candidate_lines}

请只从候选意图中选择。"""


def build_intent_judge_messages(text: str, candidates: list[IntentCandidate]) -> Messages:
    """构造意图精判消息。"""
    return [
        {"role": "system", "content": INTENT_JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": build_intent_judge_user_prompt(text, candidates)},
    ]
