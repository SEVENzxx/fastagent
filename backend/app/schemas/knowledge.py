"""知识库 Pydantic Schemas"""

from datetime import datetime

from pydantic import Field, field_serializer

from app.schemas.base import CamelModel


# ---------------------------------------------------------------------------
# 知识分块
# ---------------------------------------------------------------------------


class KnowledgeChunkResponse(CamelModel):
    """知识分块响应"""

    id: int = Field(description="分块 ID")
    doc_id: int = Field(description="所属文档 ID")
    chunk_index: int = Field(description="分块序号")
    content: str = Field(description="分块内容")
    token_count: int = Field(description="token 数量")
    metadata: dict | None = Field(default=None, description="分块元数据")
    created_at: datetime = Field(description="创建时间")

    @field_serializer("id", "doc_id")
    def serialize_bigint(self, value: int) -> str:
        return str(value)


# ---------------------------------------------------------------------------
# 知识文档
# ---------------------------------------------------------------------------


class KnowledgeDocCreate(CamelModel):
    """上传知识文档请求"""

    title: str = Field(description="文档标题")
    file_type: str = Field(description="文件类型（pdf/docx/md/txt/html）")


class KnowledgeDocUpdate(CamelModel):
    """更新知识文档请求"""

    title: str | None = Field(default=None, description="文档标题")
    status: str | None = Field(default=None, description="处理状态（processing/ready/failed）")


class KnowledgeDocResponse(CamelModel):
    """知识文档列表项响应"""

    id: int = Field(description="文档 ID")
    title: str = Field(description="文档标题")
    file_type: str = Field(description="文件类型")
    storage_path: str = Field(description="存储路径")
    status: str = Field(description="处理状态")
    chunk_count: int = Field(description="分块数量")
    product_id: int | None = Field(default=None, description="关联商品 ID")
    error_message: str | None = Field(default=None, description="错误信息")
    created_by_employee_id: int | None = Field(default=None, description="上传者员工 ID")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")

    @field_serializer("id", "product_id", "created_by_employee_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)


class KnowledgeDocDetailResponse(KnowledgeDocResponse):
    """知识文档详情（含分块列表）"""

    chunks: list[KnowledgeChunkResponse] = Field(default_factory=list, description="分块列表")


class KnowledgeDocListResponse(CamelModel):
    """知识文档列表响应"""

    items: list[KnowledgeDocResponse] = Field(description="文档列表")
    total: int = Field(description="文档总数")
