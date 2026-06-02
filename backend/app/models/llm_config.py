"""平台级 LLM 模型池 —— 统一管理所有大语言模型供应商的配置信息。

设计意图：
---------
- 租户不再直接维护供应商密钥（API Key），只保存选中的模型池记录 ID。
- 密钥字段（api_key_encrypted）只允许平台管理接口写入，任何 API 响应都不会回传原文，
  避免浏览器、日志和导出文件中泄漏密钥。
- 一个平台可能接入多个供应商（OpenAI、DeepSeek、通义千问等）和多个模型。
- 此表与 llm_usage_logs 表关联，用于统计各模型的调用量和费用。

关联关系：
---------
- LLMUsageLog.llm_config_id → 本表 id（每次 LLM 调用记录关联到具体配置）
- Tenant.selected_llm_config_id → 本表 id（租户当前选用的默认模型）
"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils.id_generator import generate_id


class LLMConfig(Base):
    """平台统一维护的 LLM 模型配置。

    业务角色：
    ---------
    充当租户 AI 功能的模型供应池。平台管理员在后台维护配置，租户管理员只能从
    已激活的记录中选择。Agent 和 RAG 回复使用租户选中的配置。

    字段说明：
    ---------
    - name: 展示名称，如 "DeepSeek V3（生产）"，便于管理员辨识。
    - provider: 供应商标识，如 openai / deepseek / qwen，用于路由到对应的 SDK。
    - api_base: 自定义 API 端点地址，支持代理或私有化部署。
    - api_key_encrypted: 经 secret_crypto 加密后的 API Key，数据库不存明文，
      任何 API 响应不返回该字段。
    - model: 实际模型名，如 gpt-4-turbo / deepseek-chat，传给供应商 API。
    - pricing: JSONB 存储价格配置，如 {"input": 0.001, "output": 0.002}（每 1K token 美元价），
      用于用量统计和成本估算。
    - purpose: 配置用途标签，当前租户对话模型使用 chat。
    - is_active: 是否启用，关闭后 Agent 不再选用此配置。
    """

    __tablename__ = "llm_configs"

    # ---- 主键 ----
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=generate_id, comment="主键")

    # ---- 基础信息 ----
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="配置名称，如 DeepSeek Chat（生产环境）")

    provider: Mapped[str] = mapped_column(String(50), nullable=False, comment="供应商标识: openai / deepseek / qwen / zhipu")

    api_base: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="自定义 API 端点地址")

    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True, comment="加密后的 API Key，API 响应永不回传")

    model: Mapped[str] = mapped_column(String(100), nullable=False, comment="实际模型名，如 gpt-4-turbo / deepseek-chat")

    # ---- 价格配置 ----
    pricing: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="价格 JSON，如 {\"input\": 0.001, \"output\": 0.002}")

    # ---- 用途与状态 ----
    purpose: Mapped[str] = mapped_column(String(50), nullable=False, default="chat", server_default="chat", comment="用途: chat / embedding / rerank / intent")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"), comment="是否启用，停用后 Agent 不再选择")

    # ---- 时间戳 ----
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="最后更新时间")

    # ---- 索引 ----
    __table_args__ = (
        # 后台按用途和启用状态筛选模型池配置。
        Index("idx_llm_configs_purpose_active", "purpose", "is_active"),
        {"comment": "平台级 LLM 模型池"},
    )
