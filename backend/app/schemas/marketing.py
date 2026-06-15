"""营销资料 Pydantic Schemas"""

from datetime import datetime

from pydantic import Field, field_serializer

from app.schemas.base import CamelModel


class MarketingDocCreate(CamelModel):
    """上传营销资料请求"""

    title: str = Field(description="资料标题")
    file_type: str = Field(description="文件类型（pdf/docx/image/link）")


class MarketingDocUpdate(CamelModel):
    """更新营销资料请求"""

    title: str | None = Field(default=None, description="资料标题")
    file_type: str | None = Field(default=None, description="文件类型")
    question_associations: list[str] | None = Field(default=None, description="关联问题列表")
    is_active: bool | None = Field(default=None, description="是否启用")


class MarketingDocResponse(CamelModel):
    """营销资料响应"""

    id: int = Field(description="资料 ID")
    title: str = Field(description="资料标题")
    file_url: str = Field(description="文件访问 URL")
    file_type: str = Field(description="文件类型")
    question_associations: list[str] | None = Field(default=None, description="关联问题列表")
    is_active: bool = Field(description="是否启用")
    created_by_employee_id: int | None = Field(default=None, description="上传者员工 ID")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")

    @field_serializer("id", "created_by_employee_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)


class MarketingDocListResponse(CamelModel):
    """营销资料列表响应"""

    items: list[MarketingDocResponse] = Field(description="资料列表")
    total: int = Field(description="资料总数")
