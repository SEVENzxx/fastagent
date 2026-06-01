"""用量与分析 Schema。"""

from datetime import datetime

from pydantic import field_serializer

from app.schemas.base import CamelModel


class LLMUsageResponse(CamelModel):
    id: int
    tenant_id: int
    llm_config_id: int | None = None
    conversation_id: int | None = None
    message_id: int | None = None
    source: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float
    latency_ms: int
    success: bool
    error_message: str | None = None
    created_at: datetime

    @field_serializer("id", "tenant_id", "llm_config_id", "conversation_id", "message_id")
    def serialize_id(self, value: int | None) -> str | None:
        return str(value) if value is not None else None


class TenantDashboardResponse(CamelModel):
    conversation_count: int
    message_count: int
    order_count: int
    knowledge_doc_count: int
    image_count: int
    llm_total_tokens: int
    llm_total_cost: float
    plan_limits: dict
