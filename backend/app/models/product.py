"""商品模型。"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.utils.id_generator import generate_id


class Product(Base):
    """租户商品目录条目。"""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, comment="租户 ID")
    category_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("categories.id"), nullable=True, comment="所属分类ID")
    name: Mapped[str] = mapped_column(String(300), nullable=False, comment="商品名称")
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="商品 SKU")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="商品描述")
    price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True, comment="价格")
    floor_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True, comment="最低报价")
    stock: Mapped[int] = mapped_column(Integer, default=0, server_default="0", comment="库存数量")
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), comment="是否为样品")
    sales_template_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="关联销售模板ID")
    specs: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="规格信息 JSON")
    qdrant_point_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="Qdrant 点 ID")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"), comment="是否上架")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")

    category: Mapped["Category | None"] = relationship("Category")

    __table_args__ = (
        Index("idx_prod_tenant_category", "tenant_id", "category_id"),
        Index("idx_prod_sku_tenant", "sku", "tenant_id", unique=True),
        Index("idx_prod_active", "is_active", postgresql_where=text("is_active = true")),
        Index("idx_prod_qdrant_point", "qdrant_point_id"),
        {"comment": "Products"},
    )
