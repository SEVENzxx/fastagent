"""意图识别与路由的共享数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


RouteType = Literal["SILENT", "GENERAL_REPLY", "AGENT", "HUMAN"]
ROUTE_TYPES = {"SILENT", "GENERAL_REPLY", "AGENT", "HUMAN"}


@dataclass(frozen=True, slots=True)
class IntentCandidate:
    """向量、关键词或融合层产生的候选意图。"""

    intent: str
    label: str
    score: float
    source: str
    matched_text: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent", _required_text(self.intent, "intent"))
        object.__setattr__(self, "label", _required_text(self.label, "label"))
        object.__setattr__(self, "score", _score(self.score))
        object.__setattr__(self, "source", _required_text(self.source, "source"))
        object.__setattr__(self, "matched_text", _optional_text(self.matched_text))
        object.__setattr__(self, "reason", _optional_text(self.reason))


@dataclass(frozen=True, slots=True)
class IntentHit:
    """单个 segment 的最终意图命中结果。"""

    segment: str
    intent: str
    label: str
    confidence: float
    route: RouteType
    skill: str | None = None
    candidates: list[IntentCandidate] = field(default_factory=list)
    ambiguous: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "segment", str(self.segment or "").strip())
        object.__setattr__(self, "intent", _required_text(self.intent, "intent"))
        object.__setattr__(self, "label", _required_text(self.label, "label"))
        object.__setattr__(self, "confidence", _score(self.confidence))
        object.__setattr__(self, "route", _route(self.route))
        object.__setattr__(self, "skill", _optional_text(self.skill))
        object.__setattr__(self, "candidates", list(self.candidates or []))
        object.__setattr__(self, "ambiguous", bool(self.ambiguous))
        object.__setattr__(self, "reason", _optional_text(self.reason))


@dataclass(frozen=True, slots=True)
class IntentResult:
    """完整意图识别结果。"""

    original_text: str
    normalized_text: str
    primary_intent: str | None
    confidence: float
    hits: list[IntentHit] = field(default_factory=list)
    candidates: list[IntentCandidate] = field(default_factory=list)
    is_multi_intent: bool = False
    need_clarification: bool = False
    source: str = "unknown"
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "original_text", str(self.original_text or ""))
        object.__setattr__(self, "normalized_text", str(self.normalized_text or "").strip())
        object.__setattr__(self, "primary_intent", _optional_text(self.primary_intent))
        object.__setattr__(self, "confidence", _score(self.confidence))
        object.__setattr__(self, "hits", list(self.hits or []))
        object.__setattr__(self, "candidates", list(self.candidates or []))
        object.__setattr__(self, "is_multi_intent", bool(self.is_multi_intent))
        object.__setattr__(self, "need_clarification", bool(self.need_clarification))
        object.__setattr__(self, "source", _required_text(self.source, "source"))
        object.__setattr__(self, "reason", _optional_text(self.reason))


@dataclass(frozen=True, slots=True)
class RoutedIntent:
    """最终路由结果，作为 MessageRouter/Executor 的输入。"""

    primary_intent: str | None
    confidence: float
    route: RouteType
    skill: str | None = None
    hits: list[IntentHit] = field(default_factory=list)
    is_multi_intent: bool = False
    need_clarification: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "primary_intent", _optional_text(self.primary_intent))
        object.__setattr__(self, "confidence", _score(self.confidence))
        object.__setattr__(self, "route", _route(self.route))
        object.__setattr__(self, "skill", _optional_text(self.skill))
        object.__setattr__(self, "hits", list(self.hits or []))
        object.__setattr__(self, "is_multi_intent", bool(self.is_multi_intent))
        object.__setattr__(self, "need_clarification", bool(self.need_clarification))
        object.__setattr__(self, "reason", _optional_text(self.reason))


@dataclass(frozen=True, slots=True)
class KeywordEntityResult:
    """关键词/实体层输出的辅助信号。"""

    keywords: list[str] = field(default_factory=list)
    entities: dict[str, list[str]] = field(default_factory=dict)
    intent_boosts: dict[str, float] = field(default_factory=dict)
    risk_flags: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PendingIntentState:
    """会话中等待用户补充的意图状态。

    例如：
    - intent=order_status
    - skill=order_status
    - required_entities=["order_no"]
    - filled_entities={}

    当用户下一轮只输入一串订单号时，ContextStateResolver 会优先把它识别为
    上一轮任务的槽位补全，而不是重新当作一条新问题做向量召回。
    """

    intent: str
    skill: str | None
    required_entities: list[str] = field(default_factory=list)
    filled_entities: dict[str, str] = field(default_factory=dict)
    last_prompt: str | None = None
    created_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent", _required_text(self.intent, "intent"))
        object.__setattr__(self, "skill", _optional_text(self.skill))
        object.__setattr__(self, "required_entities", list(self.required_entities or []))
        object.__setattr__(self, "filled_entities", dict(self.filled_entities or {}))
        object.__setattr__(self, "last_prompt", _optional_text(self.last_prompt))
        object.__setattr__(self, "created_at", _optional_text(self.created_at))


@dataclass(frozen=True, slots=True)
class FusedIntent:
    """融合打分后的 intent 级别聚合结果。"""

    intent: str
    label: str
    final_score: float
    best_score: float
    hit_count: int
    matched_examples: list[str] = field(default_factory=list)
    candidates: list[IntentCandidate] = field(default_factory=list)
    keyword_boost: float = 0.0
    context_boost: float = 0.0


@dataclass(frozen=True, slots=True)
class AmbiguityDecision:
    """歧义判断结果。"""

    intent: str
    label: str
    confidence: float
    ambiguous: bool
    need_llm: bool
    need_clarification: bool = False
    reason: str | None = None
    candidates: list[IntentCandidate] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class LLMJudgeResult:
    """LLMIntentJudge 的结构化返回。"""

    primary_intent: str
    secondary_intents: list[str] = field(default_factory=list)
    need_clarification: bool = False
    reason: str = ""


def _required_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} 不能为空")
    return text


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _score(value: float) -> float:
    score = float(value)
    if score < 0 or score > 1:
        raise ValueError("score/confidence 必须在 0 到 1 之间")
    return score


def _route(value: str) -> RouteType:
    route = _required_text(value, "route")
    if route not in ROUTE_TYPES:
        raise ValueError(f"route 必须是以下值之一: {', '.join(sorted(ROUTE_TYPES))}")
    return route  # type: ignore[return-value]
