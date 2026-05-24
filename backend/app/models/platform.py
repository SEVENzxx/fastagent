"""渠道配置模型。"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils.id_generator import generate_id


class Platform(Base):
    """第三方渠道配置。

    先支持企业微信 wecom；后续如果接入公众号、网页客服等渠道，也复用这张表。
    """

    __tablename__ = "platforms"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="wecom", server_default="wecom")
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_platforms_tenant_type", "tenant_id", "type", unique=True),
    )
