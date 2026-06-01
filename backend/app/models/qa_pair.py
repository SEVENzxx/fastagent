"""标准问答对模型。"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils.id_generator import generate_id


class QAPair(Base):
    """租户范围内的标准问题和答案。"""

    __tablename__ = "qa_pairs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, comment="租户 ID")
    question: Mapped[str] = mapped_column(Text, nullable=False, comment="标准问题")
    answer: Mapped[str] = mapped_column(Text, nullable=False, comment="标准答案")
    keywords: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="关键词列表")
    qdrant_point_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="Qdrant 点 ID")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"), comment="是否启用")
    created_by_employee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("employees.id"), nullable=True, comment="创建员工ID")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")

    __table_args__ = (
        Index("idx_qa_tenant_active", "tenant_id", "is_active"),
        Index("idx_qa_qdrant_point", "qdrant_point_id"),
        {"comment": "标准问答对"},
    )
