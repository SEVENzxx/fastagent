"""知识分块模型。

真实向量存储在 Qdrant。PostgreSQL 只保存业务字段和 qdrant_point_id，
用于链路追踪和回查。
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils.id_generator import generate_id


class KnowledgeChunk(Base):
    """由知识文档生成的最小可搜索单元。"""

    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, comment="租户 ID")
    doc_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_docs.id", ondelete="CASCADE"),
        nullable=False,
        comment="知识文档 ID",
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="分块序号")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="分块内容")
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", comment="token 数量")
    qdrant_point_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="Qdrant 点 ID")
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True, comment="扩展元数据")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")

    __table_args__ = (
        Index("idx_kc_doc", "doc_id"),
        Index("idx_kc_tenant", "tenant_id"),
        Index("idx_kc_qdrant_point", "qdrant_point_id"),
        {"comment": "知识分块"},
    )
