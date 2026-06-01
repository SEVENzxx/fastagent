"""租户模型"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func, text

from app.models.base import Base
from app.utils.id_generator import generate_id


class Tenant(Base):
    __tablename__ = "tenants"

    # ── 主键 ──────────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_id,
        comment="主键",
    )

    # ── 基本信息 ──────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="公司名称")
    slug: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="URL 标识"
    )

    # ── 套餐关联 ──────────────────────────────────────────────────────────
    plan_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("plans.id"), comment="当前套餐"
    )
    plan_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="套餐到期时间"
    )

    # ── AI / LLM 配置 ─────────────────────────────────────────────────────
    custom_prompt: Mapped[str | None] = mapped_column(Text, comment="AI 人设 Prompt")
    llm_provider: Mapped[str | None] = mapped_column(
        String(50), comment="openai / oneapi / deepseek"
    )
    llm_api_key_encrypted: Mapped[str | None] = mapped_column(
        Text, comment="加密存储的 API Key"
    )
    llm_model: Mapped[str | None] = mapped_column(String(100), comment="使用的模型名")
    oneapi_base_url: Mapped[str | None] = mapped_column(
        String(500), comment="One-API 网关地址"
    )
    selected_llm_config_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("llm_configs.id"),
        nullable=True,
        comment="租户选中的平台模型池配置。旧 LLM 字段保留用于平滑迁移。",
    )

    # ── 店铺/品牌展示 ──────────────────────────────────────────────────────
    store_showcase: Mapped[str | None] = mapped_column(
        Text, comment="品牌/店铺介绍文本。get_store_showcase skill 读取此字段，为空时返回通用兜底介绍。"
    )
    ai_greeting_message: Mapped[str | None] = mapped_column(
        Text, comment="AI 首次问候语。AI 首次介入会话时发送此消息，为空时使用默认问候。"
    )

    # ── 知识库配置 ────────────────────────────────────────────────────────
    maxkb_base_url: Mapped[str | None] = mapped_column(
        String(500), comment="MaxKB 知识库地址"
    )
    maxkb_api_key_encrypted: Mapped[str | None] = mapped_column(
        Text, comment="MaxKB API Key"
    )

    # ── 状态 ──────────────────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), comment="是否启用"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="软删除"
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

    # ── 表级约束与索引 ────────────────────────────────────────────────────
    __table_args__ = (
        Index("idx_tenants_slug", "slug", unique=True),
        Index("idx_tenants_plan", "plan_id"),
        Index("idx_tenants_selected_llm", "selected_llm_config_id"),
        {"comment": "租户表"},
    )

    # ── ORM 关系 ──────────────────────────────────────────────────────────
    plan: Mapped["Plan | None"] = relationship("Plan", lazy="selectin")  # noqa: F821
    selected_llm_config: Mapped["LLMConfig | None"] = relationship("LLMConfig", lazy="selectin")  # noqa: F821
