"""模型用量日志 —— LLM 每次调用的 token 消耗、费用和性能记录。只追加，不可修改。"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils.id_generator import generate_id


class LLMUsageLog(Base):
    """LLM 调用用量日志 —— 每次 API 调用写入一条，用于计费、故障排查和性能监控。"""

    __tablename__ = "llm_usage_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, comment="所属租户ID")
    llm_config_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("llm_configs.id"), nullable=True, comment="使用的模型配置ID")
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("conversations.id"), nullable=True, comment="关联会话ID")
    message_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("messages.id"), nullable=True, comment="关联消息ID")
    source: Mapped[str] = mapped_column(String(50), nullable=False, comment="调用来源: agent.reply / intent.classify / rag.embed / rag.rerank / agent.plan")
    model: Mapped[str] = mapped_column(String(100), nullable=False, comment="实际调用的模型名（从 LLM API 响应提取）")
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", comment="输入 token 数")
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", comment="输出 token 数")
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", comment="总 token 数")
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal("0"), server_default="0", comment="调用费用（美元）")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", comment="调用耗时（毫秒）")
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"), comment="调用是否成功")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="失败时的错误信息")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="记录创建时间")

    __table_args__ = (
        Index("idx_llm_usage_tenant_time", "tenant_id", created_at.desc()),
        Index("idx_llm_usage_conversation", "conversation_id"),
        {"comment": "LLM 调用用量日志表"},
    )
