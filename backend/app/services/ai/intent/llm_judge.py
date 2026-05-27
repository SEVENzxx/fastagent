"""LLMIntentJudge：低置信度候选精判。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from app.config import settings
from app.integrations.llm_client import LLMClient, LLMClientError
from app.services.ai.intent.types import IntentCandidate
from app.services.ai.prompts.intent_judge import INTENT_JUDGE_SYSTEM_PROMPT, build_intent_judge_user_prompt


CompletionCallable = Callable[[list[dict[str, str]]], Awaitable[str | dict[str, Any]]]


class LLMIntentJudge:
    """只允许 LLM 从候选列表中选择。"""

    def __init__(
        self,
        completion: CompletionCallable | None = None,
        client: LLMClient | None = None,
    ) -> None:
        self.client = client or LLMClient()
        self.completion = completion or self._complete_with_http

    async def judge(
        self, text: str, candidates: list[IntentCandidate]
    ) -> tuple[str, list[str], bool, str] | None:
        """执行 LLM 精判，返回 (primary_intent, secondary_intents, need_clarification, reason)。

        模型服务异常或解析失败时返回 None，让上层沿用融合打分结果。
        """
        if not candidates:
            return None

        messages = [
            {"role": "system", "content": INTENT_JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": build_intent_judge_user_prompt(text, candidates)},
        ]
        try:
            raw = await self.completion(messages)
        except LLMClientError:
            return None

        parsed = self._parse(raw)
        candidate_intents = {item.intent for item in candidates}
        primary = str(parsed.get("primary_intent") or "").strip()
        if primary not in candidate_intents:
            return None

        secondary = [
            str(item).strip()
            for item in parsed.get("secondary_intents", [])
            if str(item).strip() in candidate_intents and str(item).strip() != primary
        ]
        return (
            primary,
            secondary,
            bool(parsed.get("need_clarification", False)),
            str(parsed.get("reason") or "LLM 从候选意图中精判").strip(),
        )

    def _parse(self, raw: str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        text = str(raw or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    async def _complete_with_http(self, messages: list[dict[str, str]]) -> str:
        return await self.client.complete(
            messages,
            model=settings.AI_INTENT_JUDGE_MODEL or settings.AI_LLM_MODEL,
            max_tokens=settings.AI_INTENT_JUDGE_MAX_TOKENS,
            temperature=settings.AI_INTENT_JUDGE_TEMPERATURE,
        )
