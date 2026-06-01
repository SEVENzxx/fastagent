"""图片库模型。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils.id_generator import generate_id


class Image(Base):
    """图片库条目。

    当前语义检索使用文件名、标签等文本元数据。
    后续 CLIP 图片向量链路可以复用 qdrant_point_id。
    """

    __tablename__ = "images"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, comment="租户 ID")
    filename: Mapped[str] = mapped_column(String(300), nullable=False, comment="文件名")
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="存储路径")
    file_url: Mapped[str] = mapped_column(String(500), nullable=False, comment="访问 URL")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, comment="文件大小 (bytes)")
    mime_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="MIME 类型")
    width: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="图片宽度 (px)")
    height: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="图片高度 (px)")
    product_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=True, comment="关联商品ID")
    tags: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="标签列表")
    qdrant_point_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="Qdrant 点 ID")
    created_by_employee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("employees.id"), nullable=True, comment="上传人")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")

    __table_args__ = (
        Index("idx_img_tenant", "tenant_id"),
        Index("idx_img_product", "product_id"),
        Index("idx_img_qdrant_point", "qdrant_point_id"),
        {"comment": "图片库"},
    )
