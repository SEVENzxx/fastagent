"""分类 Schema"""

from datetime import datetime
from pydantic import Field, field_serializer, field_validator

from app.schemas.base import CamelModel


class CategoryCreate(CamelModel):
    """创建分类"""

    name: str
    parent_id: int | None = None
    sort_order: int = 0

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("分类名称不能为空")
        return value


class CategoryUpdate(CamelModel):
    """更新分类"""

    name: str | None = None
    parent_id: int | None = None
    sort_order: int | None = None


class CategoryResponse(CamelModel):
    """分类响应"""

    id: int
    tenant_id: int
    parent_id: int | None = None
    name: str
    sort_order: int
    created_at: datetime

    @field_serializer("id", "tenant_id", "parent_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)


class CategoryTreeResponse(CategoryResponse):
    """分类树节点响应"""

    children: list["CategoryTreeResponse"] = Field(default_factory=list)

    @field_serializer("id", "tenant_id", "parent_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)
