"""知识库 Pydantic Schemas"""

from datetime import datetime

from pydantic import field_serializer

from app.schemas.base import CamelModel


# ---------------------------------------------------------------------------
# 知识分块
# ---------------------------------------------------------------------------


class KnowledgeChunkResponse(CamelModel):
    """知识分块响应"""

    id: int
    doc_id: int
    chunk_index: int
    content: str
    token_count: int
    metadata: dict | None = None
    created_at: datetime

    @field_serializer("id", "doc_id")
    def serialize_bigint(self, value: int) -> str:
        return str(value)


# ---------------------------------------------------------------------------
# 知识文档
# ---------------------------------------------------------------------------


class KnowledgeDocCreate(CamelModel):
    """上传知识文档"""

    title: str
    file_type: str  # 支持 pdf / docx / md / txt / html


class KnowledgeDocUpdate(CamelModel):
    """更新知识文档"""

    title: str | None = None
    status: str | None = None  # processing / ready / failed 三种处理状态


class KnowledgeDocResponse(CamelModel):
    """知识文档列表项响应"""

    id: int
    title: str
    file_type: str
    storage_path: str
    status: str
    chunk_count: int
    error_message: str | None = None
    created_by_employee_id: int | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("id", "created_by_employee_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)


class KnowledgeDocDetailResponse(KnowledgeDocResponse):
    """知识文档详情（含分块列表）"""

    chunks: list[KnowledgeChunkResponse] = []


class KnowledgeDocListResponse(CamelModel):
    """知识文档列表响应"""

    items: list[KnowledgeDocResponse]
    total: int
