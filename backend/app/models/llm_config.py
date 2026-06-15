"""平台级 LLM 模型池 —— 统一管理所有大语言模型供应商的配置信息。"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils.id_generator import generate_id


class LLMConfig(Base):
    """平台统一维护的 LLM 模型配置。租户通过 Tenant.selected_llm_config_id 选用。"""

    __tablename__ = "llm_configs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="配置名称，如 DeepSeek Chat（生产环境）")
    provider: Mapped[str] = mapped_column(String(50), nullable=False, comment="供应商标识: openai / deepseek / qwen / zhipu")
    api_base: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="自定义 API 端点地址")
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True, comment="加密后的 API Key，API 响应永不回传")
    model: Mapped[str] = mapped_column(String(100), nullable=False, comment="实际模型名，如 gpt-4-turbo / deepseek-chat")
    pricing: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="价格 JSON，如 {\"input\": 0.001, \"output\": 0.002}")
    purpose: Mapped[str] = mapped_column(String(50), nullable=False, default="chat", server_default="chat", comment="用途: chat / embedding / rerank / intent")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"), comment="是否启用，停用后 Agent 不再选择")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="最后更新时间")

    __table_args__ = (
        Index("idx_llm_configs_purpose_active", "purpose", "is_active"),
        {"comment": "平台级 LLM 模型池"},
    )
