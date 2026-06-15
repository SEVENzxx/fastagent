"""QA 对 Pydantic Schemas"""

from datetime import datetime

from pydantic import Field, field_serializer

from app.schemas.base import CamelModel


class QAPairCreate(CamelModel):
    """创建 QA 对请求"""

    question: str = Field(description="问题")
    answer: str = Field(description="答案")
    keywords: list[str] | None = Field(default=None, description="关键词列表")


class QAPairUpdate(CamelModel):
    """更新 QA 对请求"""

    question: str | None = Field(default=None, description="问题")
    answer: str | None = Field(default=None, description="答案")
    keywords: list[str] | None = Field(default=None, description="关键词列表")
    is_active: bool | None = Field(default=None, description="是否启用")


class QAPairResponse(CamelModel):
    """QA 对响应"""

    id: int = Field(description="QA 对 ID")
    question: str = Field(description="问题")
    answer: str = Field(description="答案")
    keywords: list[str] | None = Field(default=None, description="关键词列表")
    is_active: bool = Field(description="是否启用")
    created_by_employee_id: int | None = Field(default=None, description="创建者员工 ID")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")

    @field_serializer("id", "created_by_employee_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)


class QAPairListResponse(CamelModel):
    """QA 对列表响应"""

    items: list[QAPairResponse] = Field(description="QA 对列表")
    total: int = Field(description="QA 对总数")
