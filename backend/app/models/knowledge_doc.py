"""知识文档模型"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils.id_generator import generate_id


class KnowledgeDoc(Base):
    """知识文档"""

    __tablename__ = "knowledge_docs"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=generate_id, comment="主键"
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, comment="租户ID"
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False, comment="文档标题")
    file_type: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="文件类型: pdf/docx/md/txt/html"
    )
    storage_path: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="文件存储路径"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="", comment="解析后的纯文本")
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="processing", server_default="processing",
        comment="状态: processing/ready/failed"
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="分块总数"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="解析失败原因")
    created_by_employee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id"), nullable=True, comment="上传人"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    __table_args__ = (
        Index("idx_kd_tenant_status", "tenant_id", "status"),
        {"comment": "知识文档表"},
    )
