"""平台 Admin Schema。"""

from datetime import datetime

from pydantic import Field, field_serializer, field_validator

from app.schemas.base import CamelModel


class PlanCreate(CamelModel):
    name: str
    description: str | None = None
    features: dict = Field(default_factory=dict)
    limits: dict = Field(default_factory=dict)
    price_monthly: int | None = None
    price_yearly: int | None = None
    is_active: bool = True


class PlanUpdate(CamelModel):
    name: str | None = None
    description: str | None = None
    features: dict | None = None
    limits: dict | None = None
    price_monthly: int | None = None
    price_yearly: int | None = None
    is_active: bool | None = None


class PlanResponse(CamelModel):
    id: int
    name: str
    description: str | None = None
    features: dict
    limits: dict
    price_monthly: int | None = None
    price_yearly: int | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @field_serializer("id")
    def serialize_id(self, value: int) -> str:
        return str(value)


class TenantCreate(CamelModel):
    """创建租户请求 — 超管在平台后台手动创建。

    创建租户时会自动生成一个租户级管理员账号，拥有该租户的全部业务权限
    （不含平台专有权限如 MANAGE_TENANTS / MANAGE_PLANS 等）。
    """
    name: str
    slug: str
    plan_id: int | None = None
    plan_expires_at: datetime | None = None
    custom_prompt: str | None = None
    selected_llm_config_id: int | None = None
    is_active: bool = True
    # 租户管理员账号信息
    admin_email: str
    admin_password: str
    admin_display_name: str | None = None

    @field_validator("name", "slug")
    @classmethod
    def required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("名称和企业标识不能为空")
        return value

    @field_validator("admin_email")
    @classmethod
    def email_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("管理员邮箱不能为空")
        return value.strip()

    @field_validator("admin_password")
    @classmethod
    def password_min_length(cls, value: str) -> str:
        if len(value) < 6:
            raise ValueError("管理员密码至少需要 6 个字符")
        return value


class TenantUpdate(CamelModel):
    name: str | None = None
    slug: str | None = None
    plan_id: int | None = None
    plan_expires_at: datetime | None = None
    custom_prompt: str | None = None
    store_showcase: str | None = None
    ai_greeting_message: str | None = None
    selected_llm_config_id: int | None = None
    is_active: bool | None = None


class TenantResponse(CamelModel):
    id: int
    name: str
    slug: str
    plan_id: int | None = None
    plan_name: str | None = None
    plan_expires_at: datetime | None = None
    custom_prompt: str | None = None
    selected_llm_config_id: int | None = None
    selected_llm_config_name: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @field_serializer("id", "plan_id", "selected_llm_config_id")
    def serialize_id(self, value: int | None) -> str | None:
        return str(value) if value is not None else None


class TenantCreateResponse(TenantResponse):
    """创建租户响应 — 包含自动生成的管理员账号凭证。

    注意：admin_password 仅在创建时返回一次，之后不可获取。
    超管应将密码安全地交付给租户管理员。
    """
    admin_email: str
    admin_password: str


class LLMConfigCreate(CamelModel):
    name: str
    provider: str
    api_base: str | None = None
    api_key: str | None = None
    model: str
    pricing: dict = Field(default_factory=dict)
    purpose: str = "chat"
    is_active: bool = True


class LLMConfigUpdate(CamelModel):
    name: str | None = None
    provider: str | None = None
    api_base: str | None = None
    api_key: str | None = None
    model: str | None = None
    pricing: dict | None = None
    purpose: str | None = None
    is_active: bool | None = None


class LLMConfigResponse(CamelModel):
    id: int
    name: str
    provider: str
    api_base: str | None = None
    model: str
    pricing: dict
    purpose: str
    is_active: bool
    has_api_key: bool
    created_at: datetime
    updated_at: datetime

    @field_serializer("id")
    def serialize_id(self, value: int) -> str:
        return str(value)


class AdminDashboardResponse(CamelModel):
    tenant_count: int
    active_tenant_count: int
    plan_count: int
    llm_config_count: int
    conversation_count: int
    order_count: int


class AdminConversationResponse(CamelModel):
    """跨租户会话列表项。"""

    id: int
    tenant_id: int
    tenant_name: str
    contact_name: str | None = None
    employee_name: str | None = None
    status: str
    handling_type: str
    is_transferred: bool
    last_message_at: datetime | None = None
    last_message_preview: str | None = None
    created_at: datetime

    @field_serializer("id", "tenant_id")
    def serialize_id(self, value: int) -> str:
        return str(value)


class AdminMessageResponse(CamelModel):
    """跨租户消息审计列表项。"""

    id: int
    conversation_id: int
    sender_type: str
    content_type: str
    content: str | None = None
    is_recalled: bool
    created_at: datetime

    @field_serializer("id", "conversation_id")
    def serialize_id(self, value: int) -> str:
        return str(value)


class AdminOrderResponse(CamelModel):
    """跨租户订单列表项。"""

    id: int
    tenant_id: int
    tenant_name: str
    contact_name: str | None = None
    status: str
    payable_amount: float
    created_by_type: str
    created_at: datetime
    updated_at: datetime

    @field_serializer("id", "tenant_id")
    def serialize_id(self, value: int) -> str:
        return str(value)


class AdminKnowledgeDocResponse(CamelModel):
    """跨租户知识文档状态列表项。"""

    id: int
    tenant_id: int
    tenant_name: str
    title: str
    file_type: str
    status: str
    chunk_count: int
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("id", "tenant_id")
    def serialize_id(self, value: int) -> str:
        return str(value)


class AdminPagedResponse(CamelModel):
    items: list
    total: int
    page: int
    page_size: int
