"""平台 Admin Schema。"""

from datetime import datetime

from pydantic import Field, field_serializer, field_validator

from app.schemas.base import CamelModel


class PlanCreate(CamelModel):
    """创建套餐请求"""

    name: str = Field(description="套餐名称")
    description: str | None = Field(default=None, description="套餐描述")
    features: dict = Field(default_factory=dict, description="功能特性配置")
    limits: dict = Field(default_factory=dict, description="限制配置")
    price_monthly: int | None = Field(default=None, description="月付价格（分）")
    price_yearly: int | None = Field(default=None, description="年付价格（分）")
    is_active: bool = Field(default=True, description="是否启用")


class PlanUpdate(CamelModel):
    """更新套餐请求"""

    name: str | None = Field(default=None, description="套餐名称")
    description: str | None = Field(default=None, description="套餐描述")
    features: dict | None = Field(default=None, description="功能特性配置")
    limits: dict | None = Field(default=None, description="限制配置")
    price_monthly: int | None = Field(default=None, description="月付价格（分）")
    price_yearly: int | None = Field(default=None, description="年付价格（分）")
    is_active: bool | None = Field(default=None, description="是否启用")


class PlanResponse(CamelModel):
    """套餐响应"""

    id: int = Field(description="套餐 ID")
    name: str = Field(description="套餐名称")
    description: str | None = Field(default=None, description="套餐描述")
    features: dict = Field(description="功能特性配置")
    limits: dict = Field(description="限制配置")
    price_monthly: int | None = Field(default=None, description="月付价格（分）")
    price_yearly: int | None = Field(default=None, description="年付价格（分）")
    is_active: bool = Field(description="是否启用")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")

    @field_serializer("id")
    def serialize_id(self, value: int) -> str:
        return str(value)


class TenantCreate(CamelModel):
    """创建租户请求 — 超管在平台后台手动创建。

    创建租户时会自动生成一个租户级管理员账号，拥有该租户的全部业务权限
    （不含平台专有权限如 MANAGE_TENANTS / MANAGE_PLANS 等）。
    """
    name: str = Field(description="租户名称")
    slug: str = Field(description="租户企业标识")
    plan_id: int | None = Field(default=None, description="套餐 ID")
    plan_expires_at: datetime | None = Field(default=None, description="套餐到期时间")
    custom_prompt: str | None = Field(default=None, description="自定义 prompt")
    template_json: list[str] | None = Field(default=None, description="属性模板字段名列表")
    selected_llm_config_id: int | None = Field(default=None, description="选中的 LLM 配置 ID")
    is_active: bool = Field(default=True, description="是否启用")
    # 租户管理员账号信息
    admin_email: str = Field(description="管理员邮箱")
    admin_password: str = Field(description="管理员密码")
    admin_display_name: str | None = Field(default=None, description="管理员显示名称")

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
    """更新租户请求"""

    name: str | None = Field(default=None, description="租户名称")
    slug: str | None = Field(default=None, description="租户企业标识")
    plan_id: int | None = Field(default=None, description="套餐 ID")
    plan_expires_at: datetime | None = Field(default=None, description="套餐到期时间")
    custom_prompt: str | None = Field(default=None, description="自定义 prompt")
    template_json: list[str] | None = Field(default=None, description="属性模板字段名列表")
    store_showcase: str | None = Field(default=None, description="店铺展示信息")
    ai_greeting_message: str | None = Field(default=None, description="AI 问候语")
    selected_llm_config_id: int | None = Field(default=None, description="选中的 LLM 配置 ID")
    is_active: bool | None = Field(default=None, description="是否启用")


class TenantResponse(CamelModel):
    """租户响应"""

    id: int = Field(description="租户 ID")
    name: str = Field(description="租户名称")
    slug: str = Field(description="租户企业标识")
    plan_id: int | None = Field(default=None, description="套餐 ID")
    plan_name: str | None = Field(default=None, description="套餐名称")
    plan_expires_at: datetime | None = Field(default=None, description="套餐到期时间")
    custom_prompt: str | None = Field(default=None, description="自定义 prompt")
    template_json: list[str] | None = Field(default=None, description="属性模板字段名列表")
    selected_llm_config_id: int | None = Field(default=None, description="选中的 LLM 配置 ID")
    selected_llm_config_name: str | None = Field(default=None, description="选中的 LLM 配置名称")
    is_active: bool = Field(description="是否启用")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")

    @field_serializer("id", "plan_id", "selected_llm_config_id")
    def serialize_id(self, value: int | None) -> str | None:
        return str(value) if value is not None else None


class TenantCreateResponse(TenantResponse):
    """创建租户响应 — 包含自动生成的管理员账号凭证。

    注意：admin_password 仅在创建时返回一次，之后不可获取。
    超管应将密码安全地交付给租户管理员。
    """
    admin_email: str = Field(description="管理员邮箱")
    admin_password: str = Field(description="管理员密码（仅在创建时返回）")


class LLMConfigCreate(CamelModel):
    """创建 LLM 配置请求"""

    name: str = Field(description="配置名称")
    provider: str = Field(description="LLM 提供商")
    api_base: str | None = Field(default=None, description="API 地址")
    api_key: str | None = Field(default=None, description="API 密钥")
    model: str = Field(description="模型名称")
    pricing: dict = Field(default_factory=dict, description="定价配置")
    purpose: str = Field(default="chat", description="用途（chat/embedding 等）")
    is_active: bool = Field(default=True, description="是否启用")


class LLMConfigUpdate(CamelModel):
    """更新 LLM 配置请求"""

    name: str | None = Field(default=None, description="配置名称")
    provider: str | None = Field(default=None, description="LLM 提供商")
    api_base: str | None = Field(default=None, description="API 地址")
    api_key: str | None = Field(default=None, description="API 密钥")
    model: str | None = Field(default=None, description="模型名称")
    pricing: dict | None = Field(default=None, description="定价配置")
    purpose: str | None = Field(default=None, description="用途（chat/embedding 等）")
    is_active: bool | None = Field(default=None, description="是否启用")


class LLMConfigResponse(CamelModel):
    """LLM 配置响应"""

    id: int = Field(description="配置 ID")
    name: str = Field(description="配置名称")
    provider: str = Field(description="LLM 提供商")
    api_base: str | None = Field(default=None, description="API 地址")
    model: str = Field(description="模型名称")
    pricing: dict = Field(description="定价配置")
    purpose: str = Field(description="用途")
    is_active: bool = Field(description="是否启用")
    has_api_key: bool = Field(description="是否已配置 API 密钥")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")

    @field_serializer("id")
    def serialize_id(self, value: int) -> str:
        return str(value)


class AdminDashboardResponse(CamelModel):
    """管理后台仪表盘响应"""

    tenant_count: int = Field(description="租户总数")
    active_tenant_count: int = Field(description="活跃租户数")
    plan_count: int = Field(description="套餐总数")
    llm_config_count: int = Field(description="LLM 配置总数")
    conversation_count: int = Field(description="会话总数")
    order_count: int = Field(description="订单总数")


class AdminConversationResponse(CamelModel):
    """跨租户会话列表项。"""

    id: int = Field(description="会话 ID")
    tenant_id: int = Field(description="租户 ID")
    tenant_name: str = Field(description="租户名称")
    contact_name: str | None = Field(default=None, description="客户名称")
    employee_name: str | None = Field(default=None, description="坐席名称")
    status: str = Field(description="会话状态")
    handling_type: str = Field(description="处理类型")
    is_transferred: bool = Field(description="是否已转人工")
    last_message_at: datetime | None = Field(default=None, description="最后消息时间")
    last_message_preview: str | None = Field(default=None, description="最后消息预览")
    created_at: datetime = Field(description="创建时间")

    @field_serializer("id", "tenant_id")
    def serialize_id(self, value: int) -> str:
        return str(value)


class AdminMessageResponse(CamelModel):
    """跨租户消息审计列表项。"""

    id: int = Field(description="消息 ID")
    conversation_id: int = Field(description="会话 ID")
    sender_type: str = Field(description="发送者类型")
    content_type: str = Field(description="内容类型")
    content: str | None = Field(default=None, description="消息内容")
    is_recalled: bool = Field(description="是否已撤回")
    created_at: datetime = Field(description="创建时间")

    @field_serializer("id", "conversation_id")
    def serialize_id(self, value: int) -> str:
        return str(value)


class AdminOrderResponse(CamelModel):
    """跨租户订单列表项。"""

    id: int = Field(description="订单 ID")
    tenant_id: int = Field(description="租户 ID")
    tenant_name: str = Field(description="租户名称")
    contact_name: str | None = Field(default=None, description="客户名称")
    status: str = Field(description="订单状态")
    payable_amount: float = Field(description="应付金额")
    created_by_type: str = Field(description="创建来源")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")

    @field_serializer("id", "tenant_id")
    def serialize_id(self, value: int) -> str:
        return str(value)


class AdminKnowledgeDocResponse(CamelModel):
    """跨租户知识文档状态列表项。"""

    id: int = Field(description="文档 ID")
    tenant_id: int = Field(description="租户 ID")
    tenant_name: str = Field(description="租户名称")
    title: str = Field(description="文档标题")
    file_type: str = Field(description="文件类型")
    status: str = Field(description="处理状态")
    chunk_count: int = Field(description="分块数量")
    error_message: str | None = Field(default=None, description="错误信息")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")

    @field_serializer("id", "tenant_id")
    def serialize_id(self, value: int) -> str:
        return str(value)


class AdminPagedResponse(CamelModel):
    """管理后台分页响应"""

    items: list = Field(description="数据列表")
    total: int = Field(description="数据总数")
    page: int = Field(description="当前页码")
    page_size: int = Field(description="每页数量")
