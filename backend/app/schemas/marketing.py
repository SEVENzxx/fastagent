"""营销资料 Pydantic Schemas"""

from datetime import datetime

from pydantic import field_serializer

from app.schemas.base import CamelModel


class MarketingDocCreate(CamelModel):
    """上传营销资料"""

    title: str
    file_type: str  # 支持 pdf / docx / image / link


class MarketingDocUpdate(CamelModel):
    """更新营销资料"""

    title: str | None = None
    file_type: str | None = None
    question_associations: list[str] | None = None
    is_active: bool | None = None


class MarketingDocResponse(CamelModel):
    """营销资料响应"""

    id: int
    title: str
    file_url: str
    file_type: str
    question_associations: list[str] | None = None
    is_active: bool
    created_by_employee_id: int | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("id", "created_by_employee_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)


class MarketingDocListResponse(CamelModel):
    """营销资料列表响应"""

    items: list[MarketingDocResponse]
    total: int
