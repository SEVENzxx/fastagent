"""营销资料模型。"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils.id_generator import generate_id


class MarketingDocument(Base):
    """可复用营销素材的元数据。"""

    __tablename__ = "marketing_documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, comment="租户 ID")
    title: Mapped[str] = mapped_column(String(300), nullable=False, comment="资料标题")
    file_url: Mapped[str] = mapped_column(String(500), nullable=False, comment="文件 URL")
    file_type: Mapped[str] = mapped_column(String(30), nullable=False, comment="文件类型: pdf / docx / image")
    question_associations: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="关联问题标签")
    qdrant_point_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="Qdrant 点 ID")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"), comment="是否启用")
    created_by_employee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("employees.id"), nullable=True, comment="上传员工ID")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")

    __table_args__ = (
        Index("idx_md_tenant_active", "tenant_id", "is_active"),
        Index("idx_md_qdrant_point", "qdrant_point_id"),
        {"comment": "营销资料"},
    )
