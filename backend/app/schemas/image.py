"""图片库 Pydantic Schemas"""

from datetime import datetime

from pydantic import Field, field_serializer

from app.schemas.base import CamelModel


class ImageUpdate(CamelModel):
    """更新图片信息请求"""

    tags: list[str] | None = Field(default=None, description="图片标签")
    product_id: int | None = Field(default=None, description="关联商品 ID")


class ImageResponse(CamelModel):
    """图片响应"""

    id: int = Field(description="图片 ID")
    filename: str = Field(description="文件名")
    storage_path: str = Field(description="存储路径")
    file_url: str = Field(description="访问 URL")
    file_size: int = Field(description="文件大小（字节）")
    mime_type: str = Field(description="MIME 类型")
    width: int | None = Field(default=None, description="图片宽度（像素）")
    height: int | None = Field(default=None, description="图片高度（像素）")
    product_id: int | None = Field(default=None, description="关联商品 ID")
    tags: list[str] | None = Field(default=None, description="图片标签列表")
    created_by_employee_id: int | None = Field(default=None, description="上传者员工 ID")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")

    @field_serializer("id", "product_id", "created_by_employee_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)


class ImageListResponse(CamelModel):
    """图片列表响应"""

    items: list[ImageResponse] = Field(description="图片列表")
    total: int = Field(description="图片总数")
