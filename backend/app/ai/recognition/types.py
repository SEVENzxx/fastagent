"""RecognitionPipeline 输出类型。

RecognitionPipeline 只做场景识别，不解析业务 ID。
业务 ID 映射由 Component 层完成。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SkillName(str, Enum):
    """一级 skill 路由结果。"""
    TEMPLATE = "TEMPLATE"
    PRODUCT = "PRODUCT"
    ORDER = "ORDER"
    RAG = "RAG"
    MEMORY = "MEMORY"
    HUMAN = "HUMAN"
    FALLBACK = "FALLBACK"


class RiskLevel(str, Enum):
    """操作风险等级。"""
    READ_ONLY = "READ_ONLY"
    LOW_RISK_WRITE = "LOW_RISK_WRITE"
    HIGH_RISK_WRITE = "HIGH_RISK_WRITE"


class IntentCandidate(BaseModel):
    """向量召回或融合层产出的候选意图。"""
    intent: str
    label: str
    score: float
    skill: SkillName
    source: str = "vector"
    matched_text: str | None = None


class ScenarioDecision(BaseModel):
    """场景识别结果。

    RecognitionPipeline 唯一输出。
    entities 只包含粗文本和值，不包含业务 ID。
    """

    scenario_id: str                             # 场景标识
    confidence: float                            # 置信度 [0, 1]
    entities: dict[str, Any] = Field(default_factory=dict)  # 粗实体（不含业务 ID）
