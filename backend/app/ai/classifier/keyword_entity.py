"""KeywordEntityExtractor：关键词/实体识别。"""

from __future__ import annotations

import re
from collections import defaultdict

from app.ai.classifier.intent_config import DEFAULT_INTENT_CONFIG, IntentRecognitionConfig
from app.ai.classifier.types import KeywordEntityResult


ENTITY_PATTERNS: dict[str, re.Pattern[str]] = {
    "phone": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "amount": re.compile(r"\d+(?:\.\d+)?\s*(?:元|块|人民币|rmb)", re.IGNORECASE),
    "order_no": re.compile(r"(?:订单号?|订单)\s*[:：]?\s*([A-Za-z0-9\-]{8,32})"),
    "tracking_no": re.compile(r"(?:快递单号?|物流单号?)\s*[:：]?\s*([A-Za-z0-9]{8,32})"),
    "product_model": re.compile(r"\b[A-Za-z]{1,6}\d{2,}[A-Za-z0-9\-]*\b"),
}


class KeywordEntityExtractor:
    """抽取关键词、实体和 intent 加权信号。"""

    def __init__(self, config: IntentRecognitionConfig | None = None) -> None:
        self.config = config or DEFAULT_INTENT_CONFIG

    def extract(self, normalized_text: str) -> KeywordEntityResult:
        """返回辅助信号，不直接决定最终 intent。"""
        keywords: list[str] = []
        boosts: defaultdict[str, float] = defaultdict(float)
        risk_flags: list[str] = []
        text = normalized_text.lower()

        for item in self.config.keyword_boosts:
            if item.keyword.lower() in text:
                keywords.append(item.keyword)
                boosts[item.intent] += item.boost

        entities = {
            name: [match.group(1) if match.groups() else match.group(0) for match in pattern.finditer(normalized_text)]
            for name, pattern in ENTITY_PATTERNS.items()
        }
        entities = {name: values for name, values in entities.items() if values}

        if "phone" in entities:
            risk_flags.append("contains_phone")

        return KeywordEntityResult(
            keywords=keywords,
            entities=entities,
            intent_boosts=dict(boosts),
            risk_flags=risk_flags,
        )
