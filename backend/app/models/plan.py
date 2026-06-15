"""订阅套餐模型 — 平台级，不绑定 tenant_id。"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, JSON, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils.id_generator import generate_id


class Plan(Base):
    """订阅套餐方案。平台级资源，超级管理员统一维护。租户通过 tenants.plan_id 关联。"""

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, comment="套餐名称（全局唯一）")
    description: Mapped[str | None] = mapped_column(Text, comment="套餐简介")
    features: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, comment="功能开关 JSON")
    limits: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, comment="限额配置 JSON")
    price_monthly: Mapped[int | None] = mapped_column(Integer, comment="月费（单位：分）")
    price_yearly: Mapped[int | None] = mapped_column(Integer, comment="年费（单位：分）")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"), comment="是否上架")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="最后更新时间")
