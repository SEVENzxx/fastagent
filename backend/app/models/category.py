"""商品分类模型"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.utils.id_generator import generate_id


class Category(Base):
    """商品分类（支持多级树形结构）"""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=generate_id, comment="主键"
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, comment="租户ID"
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("categories.id"), nullable=True, comment="父分类ID"
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="分类名称")
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", comment="排序"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )

    # ── 关联 ──
    parent: Mapped["Category | None"] = relationship(
        "Category", remote_side=[id], back_populates="children"
    )
    children: Mapped[list["Category"]] = relationship(
        "Category", back_populates="parent", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_cat_tenant_parent", "tenant_id", "parent_id"),
        {"comment": "商品分类表"},
    )
