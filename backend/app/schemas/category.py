"""分类 Schema"""

from datetime import datetime
from pydantic import Field, field_serializer, field_validator

from app.schemas.base import CamelModel


class CategoryCreate(CamelModel):
    """创建分类请求"""

    name: str = Field(description="分类名称")
    parent_id: int | None = Field(default=None, description="父分类 ID")
    sort_order: int = Field(default=0, description="排序序号")

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("分类名称不能为空")
        return value


class CategoryUpdate(CamelModel):
    """更新分类请求"""

    name: str | None = Field(default=None, description="分类名称")
    parent_id: int | None = Field(default=None, description="父分类 ID")
    sort_order: int | None = Field(default=None, description="排序序号")


class CategoryResponse(CamelModel):
    """分类响应"""

    id: int = Field(description="分类 ID")
    tenant_id: int = Field(description="租户 ID")
    parent_id: int | None = Field(default=None, description="父分类 ID")
    name: str = Field(description="分类名称")
    sort_order: int = Field(description="排序序号")
    created_at: datetime = Field(description="创建时间")

    @field_serializer("id", "tenant_id", "parent_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)


class CategoryTreeResponse(CategoryResponse):
    """分类树节点响应"""

    children: list["CategoryTreeResponse"] = Field(default_factory=list, description="子分类列表")

    @field_serializer("id", "tenant_id", "parent_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)
