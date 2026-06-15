"""场景样本 Pydantic Schemas"""

from datetime import datetime

from pydantic import Field, field_serializer, field_validator

from app.schemas.base import CamelModel


# ── 请求 ──


class IntentSampleCreate(CamelModel):
    """新增场景样本请求"""

    scenario_id: str = Field(description="场景标识，如 product.catalog")
    label: str = Field(description="场景中文标签")
    example_text: str = Field(description="示例文本")
    enabled: bool = Field(default=True, description="是否启用")

    @field_validator("scenario_id")
    @classmethod
    def validate_scenario_id(cls, v: str) -> str:
        text = (v or "").strip()
        if not text:
            raise ValueError("scenario_id 不能为空")
        if "." not in text:
            raise ValueError("scenario_id 必须包含点号，如 product.catalog")
        return text

    @field_validator("example_text")
    @classmethod
    def validate_example_text(cls, v: str) -> str:
        text = (v or "").strip()
        if not text:
            raise ValueError("example_text 不能为空")
        return text


class IntentSampleUpdate(CamelModel):
    """编辑场景样本请求"""

    scenario_id: str | None = Field(default=None, description="场景标识")
    label: str | None = Field(default=None, description="场景中文标签")
    example_text: str | None = Field(default=None, description="示例文本")
    enabled: bool | None = Field(default=None, description="是否启用")

    @field_validator("scenario_id")
    @classmethod
    def validate_scenario_id(cls, v: str | None) -> str | None:
        if v is None:
            return v
        text = v.strip()
        if not text:
            raise ValueError("scenario_id 不能为空")
        if "." not in text:
            raise ValueError("scenario_id 必须包含点号，如 product.catalog")
        return text

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
    """批量新增场景样本请求"""

    scenario_id: str = Field(description="场景标识")
    label: str = Field(description="场景中文标签")
    examples: list[str] = Field(description="示例文本列表")
    enabled: bool = Field(default=True, description="是否启用")

    @field_validator("scenario_id")
    @classmethod
    def validate_scenario_id(cls, v: str) -> str:
        text = (v or "").strip()
        if not text:
            raise ValueError("scenario_id 不能为空")
        if "." not in text:
            raise ValueError("scenario_id 必须包含点号，如 product.catalog")
        return text


class IntentSampleTestSearch(CamelModel):
    """测试向量召回请求"""

    query: str = Field(description="测试查询文本")


# ── 响应 ──


class IntentSampleResponse(CamelModel):
    """场景样本响应"""

    id: int = Field(description="样本 ID")
    tenant_id: int = Field(description="租户 ID")
    scenario_id: str = Field(description="场景标识")
    label: str = Field(description="场景中文标签")
    example_text: str = Field(description="示例文本")
    enabled: bool = Field(description="是否启用")
    source: str = Field(description="样本来源")
    schema_version: int = Field(description="Schema 版本号")
    qdrant_point_id: str | None = Field(default=None, description="Qdrant 向量点 ID")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")

    @field_serializer("id", "tenant_id")
    def serialize_bigint(self, value: int) -> str:
        return str(value)


class IntentSampleListResponse(CamelModel):
    """场景样本列表响应"""

    items: list[IntentSampleResponse] = Field(description="样本列表")
    total: int = Field(description="样本总数")


class IntentSampleTestHit(CamelModel):
    """测试召回结果项"""

    scenario_id: str = Field(description="场景标识")
    label: str = Field(description="场景中文标签")
    score: float = Field(description="相似度分数")
    example_text: str = Field(description="匹配的示例文本")
    source: str = Field(description="样本来源")
    tenant_id: int = Field(description="租户 ID")


class IntentSampleTestSearchResponse(CamelModel):
    """测试召回结果响应"""

    query: str = Field(description="查询文本")
    results: list[IntentSampleTestHit] = Field(description="召回结果列表")


class SkillOption(CamelModel):
    """Skill 枚举选项"""

    value: str = Field(description="Skill 值")
    label: str = Field(description="Skill 中文标签")


class RiskLevelOption(CamelModel):
    """风险等级枚举选项"""

    value: str = Field(description="风险等级值")
    label: str = Field(description="风险等级中文标签")
