"""模型用量日志 —— LLM 每次调用的 token 消耗、费用和性能记录。

设计意图：
---------
这是一张纯追加写（append-only）的日志表，记录每一次 LLM API 调用的计量数据。
它同时承担两个职责：

1. **计费依据**：按租户 + 时间聚合 token 消耗和费用，用于生成账单和用量报表。
2. **故障排查**：按会话或消息 ID 追溯某次 Agent 交互中 LLM 调用的 model、token、
   耗时和成功/失败状态，帮助定位 AI 回复质量问题和性能瓶颈。

重要约定：
---------
- 费用字段（cost）使用 SQLAlchemy Numeric → Python Decimal 类型，避免浮点数
  累加导致的精度误差（这对财务对账至关重要）。
- 此表只追加不更新/不删除，确保审计轨迹完整。
- 每次 LLM API 调用（chat completion、embedding、rerank 等）都必须写入一条记录，
  无论成功还是失败。

关联关系：
---------
- tenant_id → tenants.id（按租户聚合用量）
- llm_config_id → llm_configs.id（追溯使用了哪个模型配置）
- conversation_id → conversations.id（追溯到具体会话）
- message_id → messages.id（追溯到具体消息）

字段说明：
---------
- source: 调用来源模块，如 "agent.reply" / "intent.classify" / "rag.embed" / "rag.rerank"。
- model: 实际调用的模型名（从 LLM API 响应中提取，用于校验配置是否一致）。
- prompt_tokens / completion_tokens: 输入和输出 token 数。
- total_tokens: prompt + completion 的总和（冗余存储，加速聚合查询）。
- cost: 本次调用的费用 = pricing × token 数，NUMERIC(12,6) 最高 999999.999999。
- latency_ms: 调用耗时（毫秒），用于性能监控和异常检测。
- success: 是否成功，失败时查看 error_message。
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils.id_generator import generate_id


class LLMUsageLog(Base):
    """LLM 调用用量日志 —— 追加写入，不可修改。

    业务角色：
    ---------
    系统内部每发起一次 LLM API 请求（对话生成、意图识别、向量嵌入、重排序等），
    在获得 API 响应后立即写入一条用量日志。这是全平台 LLM 资源消耗的唯一权威
    记录来源。

    使用场景：
    ---------
    - 平台运营查看各租户的 token 消耗趋势图（按天/周聚合 total_tokens）。
    - 财务对账：按租户聚合 cost 生成月度账单。
    - 故障排查：查询某会话的所有 LLM 调用记录，检查成功率和耗时。
    - 性能监控：按 source 聚合 latency_ms，识别慢调用。
    - 成本优化：按 model 聚合 cost 和 total_tokens，发现高成本对话模式。
    """

    __tablename__ = "llm_usage_logs"

    # ---- 主键 ----
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")

    # ---- 归属 ----
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, comment="所属租户ID")

    # ---- 关联 ----
    llm_config_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("llm_configs.id"), nullable=True, comment="使用的模型配置ID")

    conversation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("conversations.id"), nullable=True, comment="关联会话ID")

    message_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("messages.id"), nullable=True, comment="关联消息ID")

    # ---- 调用信息 ----
    source: Mapped[str] = mapped_column(String(50), nullable=False, comment="调用来源: agent.reply / intent.classify / rag.embed / rag.rerank / agent.plan")

    model: Mapped[str] = mapped_column(String(100), nullable=False, comment="实际调用的模型名（从 LLM API 响应提取）")

    # ---- Token 用量 ----
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", comment="输入 token 数")

    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", comment="输出 token 数")

    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", comment="总 token 数（冗余存储加速聚合）")

    # ---- 费用 ----
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal("0"), server_default="0", comment="调用费用（美元），NUMERIC(12,6) 精度")

    # ---- 性能 ----
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", comment="调用耗时（毫秒）")

    # ---- 结果 ----
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"), comment="调用是否成功")

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="失败时的错误信息")

    # ---- 时间戳 ----
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="记录创建时间")

    # ---- 索引 ----
    __table_args__ = (
        # 租户维度按时间倒序：用量报表、账单生成、后台查询的核心索引
        Index("idx_llm_usage_tenant_time", "tenant_id", created_at.desc()),
        # 按会话检索该会话的所有 LLM 调用：故障排查和对话质量分析
        Index("idx_llm_usage_conversation", "conversation_id"),
    )
