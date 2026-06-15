"""用量与分析 Schema。"""

from datetime import datetime

from pydantic import Field, field_serializer

from app.schemas.base import CamelModel


class LLMUsageResponse(CamelModel):
    """LLM 用量记录响应"""

    id: int = Field(description="记录 ID")
    tenant_id: int = Field(description="租户 ID")
    llm_config_id: int | None = Field(default=None, description="LLM 配置 ID")
    conversation_id: int | None = Field(default=None, description="会话 ID")
    message_id: int | None = Field(default=None, description="消息 ID")
    source: str = Field(description="调用来源")
    model: str = Field(description="模型名称")
    prompt_tokens: int = Field(description="提示 tokens 数")
    completion_tokens: int = Field(description="生成 tokens 数")
    total_tokens: int = Field(description="总 tokens 数")
    cost: float = Field(description="调用成本")
    latency_ms: int = Field(description="延迟毫秒数")
    success: bool = Field(description="调用是否成功")
    error_message: str | None = Field(default=None, description="错误信息")
    created_at: datetime = Field(description="创建时间")

    @field_serializer("id", "tenant_id", "llm_config_id", "conversation_id", "message_id")
    def serialize_id(self, value: int | None) -> str | None:
        return str(value) if value is not None else None


class TenantDashboardResponse(CamelModel):
    """租户仪表盘响应"""

    conversation_count: int = Field(description="会话总数")
    message_count: int = Field(description="消息总数")
    order_count: int = Field(description="订单总数")
    knowledge_doc_count: int = Field(description="知识文档总数")
    image_count: int = Field(description="图片总数")
    llm_total_tokens: int = Field(description="LLM 总 tokens 消耗")
    llm_total_cost: float = Field(description="LLM 总成本")
    plan_limits: dict = Field(description="套餐限制信息")
