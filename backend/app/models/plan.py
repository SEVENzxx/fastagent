"""订阅套餐模型 — 定义租户可订阅的 SaaS 套餐方案。

设计意图
--------
Plan 是平台级资源（不绑定 tenant_id），由超级管理员统一维护。
每个租户通过 tenants.plan_id 关联到一个套餐，系统根据套餐的 limits
（限额配置）和 features（功能开关）来控制租户的功能可用性和资源上限。

字段说明
--------
- name: 套餐名称（全局唯一），如 "Free"、"Pro"、"Enterprise"
- features: JSONB 功能开关，如 {"ai_agent": true, "rag": true, "analytics": false}
- limits: JSONB 限额配置，如 {"max_employees": 5, "max_conversations": 500, "max_storage_gb": 10}
- price_monthly / price_yearly: 价格（单位：分），避免浮点数精度问题
- is_active: 是否上架（下架的套餐不影响已订阅的租户）

关联关系
--------
- Tenant.plan_id → Plan.id（多对一，每个租户关联一个套餐）
- Tenant.plan_expires_at → 套餐到期时间（到期后仍保留关联但不享受服务）
"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func, text

from app.models.base import Base
from app.utils.id_generator import generate_id


class Plan(Base):
    """订阅套餐方案。

    平台级资源（无 tenant_id），由超级管理员在 Admin 后台统一管理。
    套餐通过 tenants.plan_id 与租户关联，系统在运行时根据 limits 做配额校验。
    """

    __tablename__ = "plans"

    # ── 主键 ──
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_id,
        comment="主键",
    )

    # ── 基本信息 ──
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, comment="套餐名称（全局唯一，如 Free/Pro/Enterprise）"
    )
    description: Mapped[str | None] = mapped_column(Text, comment="套餐简介（前端展示用）")

    # ── 功能与限额 ──
    features: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment='功能开关 JSONB: {"ai_agent": true, "rag": true, "analytics": false}'
    )
    limits: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment='限额配置 JSONB: {"max_employees": 5, "max_conversations": 500, "max_storage_gb": 10}'
    )

    # ── 价格 ──
    price_monthly: Mapped[int | None] = mapped_column(
        Integer, comment="月费（单位：分，避免浮点精度问题）"
    )
    price_yearly: Mapped[int | None] = mapped_column(
        Integer, comment="年费（单位：分）"
    )

    # ── 状态 ──
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"),
        comment="是否上架（下架不影响已订阅租户）"
    )

    # ── 时间戳 ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="最后更新时间"
    )
