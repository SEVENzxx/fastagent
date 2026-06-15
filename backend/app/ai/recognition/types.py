"""RecognitionPipeline 输出类型。

RecognitionPipeline 只做场景识别，不解析业务 ID。
业务 ID 映射由 Component 层完成。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.common.enums.base import LabeledEnum


class SkillName(LabeledEnum):
    """一级 skill 路由结果。"""
    TEMPLATE = "TEMPLATE"
    PRODUCT = "PRODUCT"
    ORDER = "ORDER"
    RAG = "RAG"
    MEMORY = "MEMORY"
    HUMAN = "HUMAN"
    FALLBACK = "FALLBACK"

    @property
    def label(self) -> str:
        labels = {
            SkillName.TEMPLATE: "模板回复",
            SkillName.PRODUCT: "商品",
            SkillName.ORDER: "订单",
            SkillName.RAG: "知识库",
            SkillName.MEMORY: "记忆",
            SkillName.HUMAN: "转人工",
            SkillName.FALLBACK: "降级回复",
        }
        return labels[self]


class RiskLevel(LabeledEnum):
    """操作风险等级。"""
    READ_ONLY = "READ_ONLY"
    LOW_RISK_WRITE = "LOW_RISK_WRITE"
    HIGH_RISK_WRITE = "HIGH_RISK_WRITE"

    @property
    def label(self) -> str:
        labels = {
            RiskLevel.READ_ONLY: "只读",
            RiskLevel.LOW_RISK_WRITE: "低风险写",
            RiskLevel.HIGH_RISK_WRITE: "高风险写",
        }
        return labels[self]


class IntentCandidate(BaseModel):
    """向量召回或融合层产出的候选意图。"""

    scenario_id: str = Field(description="场景标识（如 product.catalog）")
    label: str = Field(description="意图中文标签")
    score: float = Field(description="置信度 [0, 1]")
    skill: SkillName = Field(description="所属 Skill")
    source: str = Field(default="vector", description="候选来源（vector/rule/fusion）")
    matched_text: str | None = Field(None, description="匹配到的原文片段")


class ScenarioDecision(BaseModel):
    """场景识别结果。

    RecognitionPipeline 唯一输出。
    entities 只包含粗文本和值，不包含业务 ID。
    """

    scenario_id: str = Field(description="场景标识")
    confidence: float = Field(description="置信度 [0, 1]")
    entities: dict[str, Any] = Field(default_factory=dict, description="粗实体（不含业务 ID）")
