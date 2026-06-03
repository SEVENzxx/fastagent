"""LLMIntentJudge — 低置信度候选精判，仅模糊样本触发。"""

from __future__ import annotations

import json
from typing import Any

from app.ai.classifier.types import IntentCandidate
from app.ai.llm.gateway import LLMClientError, LLMUseCase, complete
from app.ai.llm.prompts.intent_judge import build_intent_judge_messages


class LLMIntentJudge:
    """LLM 精判：只允许从候选列表中选，不允许自由发挥。"""

    async def judge(
        self, text: str, candidates: list[IntentCandidate]
    ) -> tuple[str, list[str], bool, str] | None:
        """返回 (primary_intent, secondary_intents, need_clarification, reason)，异常时返回 None。"""
        if not candidates:
            return None

        try:
            raw = await complete(
                LLMUseCase.INTENT_JUDGE,
                build_intent_judge_messages(text, candidates),
                max_tokens=64,
                temperature=0.0,
            )
        except LLMClientError:
            return None

        parsed = self._parse(raw)
        candidate_set = {item.intent for item in candidates}
        primary = str(parsed.get("primary_intent") or "").strip()
        if primary not in candidate_set:
            return None  # LLM 输出的意图不在候选集中，视为不可信

        secondary = [
            str(item).strip()
            for item in parsed.get("secondary_intents", [])
            if str(item).strip() in candidate_set and str(item).strip() != primary
        ]
        return (
            primary,
            secondary,
            bool(parsed.get("need_clarification", False)),
            str(parsed.get("reason") or "LLM 从候选意图中精判").strip(),
        )

    def _parse(self, raw: str | dict[str, Any]) -> dict[str, Any]:
        """容错解析 LLM 返回的 JSON，含 Markdown 代码块剥离。"""
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
