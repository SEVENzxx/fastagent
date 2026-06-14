"""意图样本 Pydantic Schemas"""

from datetime import datetime

from pydantic import field_serializer, field_validator

from app.ai.recognition.types import RiskLevel, SkillName
from app.schemas.base import CamelModel


# ── 请求 ──


class IntentSampleCreate(CamelModel):
    """新增意图样本"""

    intent: str
    label: str
    skill: str
    risk_level: str
    example_text: str
    enabled: bool = True

    @field_validator("skill")
    @classmethod
    def validate_skill(cls, v: str) -> str:
        allowed = {e.value for e in SkillName}
        if v not in allowed:
            raise ValueError(f"skill 必须是 {allowed} 之一")
        return v

    @field_validator("risk_level")
    @classmethod
    def validate_risk_level(cls, v: str) -> str:
        allowed = {e.value for e in RiskLevel}
        if v not in allowed:
            raise ValueError(f"risk_level 必须是 {allowed} 之一")
        return v

    @field_validator("example_text")
    @classmethod
    def validate_example_text(cls, v: str) -> str:
        text = (v or "").strip()
        if not text:
            raise ValueError("example_text 不能为空")
        return text


class IntentSampleUpdate(CamelModel):
    """编辑意图样本"""

    intent: str | None = None
    label: str | None = None
    skill: str | None = None
    risk_level: str | None = None
    example_text: str | None = None
    enabled: bool | None = None

    @field_validator("skill")
    @classmethod
    def validate_skill(cls, v: str | None) -> str | None:
        if v is None:
            return v
        allowed = {e.value for e in SkillName}
        if v not in allowed:
            raise ValueError(f"skill 必须是 {allowed} 之一")
        return v

    @field_validator("risk_level")
    @classmethod
    def validate_risk_level(cls, v: str | None) -> str | None:
        if v is None:
            return v
        allowed = {e.value for e in RiskLevel}
        if v not in allowed:
            raise ValueError(f"risk_level 必须是 {allowed} 之一")
        return v

    @field_validator("example_text")
    @classmethod
    def validate_example_text(cls, v: str | None) -> str | None:
        if v is None:
            return v
        text = (v or "").strip()
        if not text:
            raise ValueError("example_text 不能为空")
        return text


class IntentSampleBatchCreate(CamelModel):
    """批量新增意图样本 — 共享 intent / label / skill / risk_level / enabled"""

    intent: str
    label: str
    skill: str
    risk_level: str
    examples: list[str]
    enabled: bool = True

    @field_validator("skill")
    @classmethod
    def validate_skill(cls, v: str) -> str:
        allowed = {e.value for e in SkillName}
        if v not in allowed:
            raise ValueError(f"skill 必须是 {allowed} 之一")
        return v

    @field_validator("risk_level")
    @classmethod
    def validate_risk_level(cls, v: str) -> str:
        allowed = {e.value for e in RiskLevel}
        if v not in allowed:
            raise ValueError(f"risk_level 必须是 {allowed} 之一")
        return v


class IntentSampleTestSearch(CamelModel):
    """测试向量召回"""
    query: str


# ── 响应 ──


class IntentSampleResponse(CamelModel):
    """意图样本响应"""

    id: int
    tenant_id: int
    intent: str
    label: str
    skill: str
    risk_level: str
    example_text: str
    enabled: bool
    source: str
    schema_version: int
    qdrant_point_id: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("id", "tenant_id")
    def serialize_bigint(self, value: int) -> str:
        return str(value)


class IntentSampleListResponse(CamelModel):
    """意图样本列表响应"""

    items: list[IntentSampleResponse]
    total: int


class IntentSampleTestHit(CamelModel):
    """测试召回结果项"""
    intent: str
    label: str
    skill: str
    score: float
    example_text: str
    source: str
    tenant_id: int


class IntentSampleTestSearchResponse(CamelModel):
    """测试召回结果"""
    query: str
    results: list[IntentSampleTestHit]


class SkillOption(CamelModel):
    """Skill 枚举选项"""
    value: str
    label: str


class RiskLevelOption(CamelModel):
    """风险等级枚举选项"""
    value: str
    label: str
