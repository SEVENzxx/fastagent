"""订阅套餐模型"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func, text

from app.models.base import Base


class Plan(Base):
    __tablename__ = "plans"

    # ── 主键 ──────────────────────────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
        comment="主键",
    )

    # ── 基本信息 ──────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, comment="套餐名: Free/Pro/Enterprise"
    )
    description: Mapped[str | None] = mapped_column(Text, comment="套餐描述")

    # ── 功能与限额 ────────────────────────────────────────────────────────
    features: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        comment='JSONB: {"ai_agent": true, "rag": true, "analytics": false}',
    )
    limits: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        comment='JSONB: {"max_employees": 5, "max_conversations": 500, "max_storage_gb": 10}',
    )

    # ── 价格 ──────────────────────────────────────────────────────────────
    price_monthly: Mapped[int | None] = mapped_column(Integer, comment="月费(分)")
    price_yearly: Mapped[int | None] = mapped_column(Integer, comment="年费(分)")

    # ── 状态 ──────────────────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), comment="是否上架"
    )

    # ── 时间戳 ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )
