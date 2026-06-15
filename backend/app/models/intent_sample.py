"""场景样本模型 — 租户自定义场景向量召回样本。

租户可通过管理后台自定义场景样本，覆盖具体品类/属性/品牌/行业表达。
平台默认样本（tenant_id=0）由 bootstrap 在启动时自动写入 Qdrant。
每个样本在 Qdrant 中对应一个向量 point，搜索时同时召回 tenant_id 和 0 的样本。
"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils.id_generator import generate_id


class IntentSample(Base):
    """租户自定义场景样本。skill 和 risk_level 由 _SCENARIO_SKILL_MAP 自动推导。"""

    __tablename__ = "intent_samples"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, comment="租户ID")
    scenario_id: Mapped[str] = mapped_column(String(100), nullable=False, comment="场景标识: product.catalog / order.list / …")
    label: Mapped[str] = mapped_column(String(100), nullable=False, comment="场景中文名称")
    example_text: Mapped[str] = mapped_column(Text, nullable=False, comment="用户样本文本")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true", comment="是否启用")
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="tenant_custom", server_default="tenant_custom", comment="来源: platform_default / tenant_custom")
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3", comment="写入时的 SCHEMA_VERSION")
    qdrant_point_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="Qdrant point ID，用于删除时定位")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")

    __table_args__ = (
        CheckConstraint("char_length(example_text) > 0", name="ck_intent_samples_example_text"),
        Index("idx_intent_samples_tenant", "tenant_id"),
        Index("idx_intent_samples_tenant_scenario", "tenant_id", "scenario_id"),
        Index("idx_intent_samples_uniq", "tenant_id", "scenario_id", "example_text", unique=True),
        {"comment": "租户自定义场景样本表"},
    )
