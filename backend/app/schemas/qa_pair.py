"""QA 对 Pydantic Schemas"""

from datetime import datetime

from pydantic import field_serializer

from app.schemas.base import CamelModel


class QAPairCreate(CamelModel):
    """创建 QA 对"""

    question: str
    answer: str
    keywords: list[str] | None = None


class QAPairUpdate(CamelModel):
    """更新 QA 对"""

    question: str | None = None
    answer: str | None = None
    keywords: list[str] | None = None
    is_active: bool | None = None


class QAPairResponse(CamelModel):
    """QA 对响应"""

    id: int
    question: str
    answer: str
    keywords: list[str] | None = None
    is_active: bool
    created_by_employee_id: int | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("id", "created_by_employee_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)


class QAPairListResponse(CamelModel):
    """QA 对列表响应"""

    items: list[QAPairResponse]
    total: int
