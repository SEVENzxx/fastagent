"""图片库 Pydantic Schemas"""

from datetime import datetime

from pydantic import field_serializer

from app.schemas.base import CamelModel


class ImageUpdate(CamelModel):
    """更新图片信息"""

    tags: list[str] | None = None
    product_id: int | None = None


class ImageResponse(CamelModel):
    """图片响应"""

    id: int
    filename: str
    storage_path: str
    file_url: str
    file_size: int
    mime_type: str
    width: int | None = None
    height: int | None = None
    product_id: int | None = None
    tags: list[str] | None = None
    created_by_employee_id: int | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("id", "product_id", "created_by_employee_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)


class ImageListResponse(CamelModel):
    """图片列表响应"""

    items: list[ImageResponse]
    total: int
