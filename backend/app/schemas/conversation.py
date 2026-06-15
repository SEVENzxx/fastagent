"""会话与消息 Schema"""

from datetime import datetime

from pydantic import Field, field_serializer, field_validator

from app.models.conversation import Conversation
from app.schemas.base import CamelModel

CONVERSATION_STATUSES = {
    Conversation.STATUS_AI_PROCESSING,
    Conversation.STATUS_PENDING_HUMAN,
    Conversation.STATUS_HUMAN_PROCESSING,
    Conversation.STATUS_CLOSED,
}
HANDLING_TYPES = {
    Conversation.HANDLING_AI_ONLY,
    Conversation.HANDLING_HUMAN,
}
SENDER_TYPES = {
    Conversation.SENDER_AI,
    Conversation.SENDER_AGENT,
    Conversation.SENDER_CUSTOMER,
    Conversation.SENDER_SYSTEM,
}
CONTENT_TYPES = {"text", "image", "voice", "file", "card", "event"}


class ConversationCreate(CamelModel):
    """创建会话"""

    contact_id: int = Field(description="客户联系人 ID")
    employee_id: int | None = Field(None, description="坐席员工 ID（预分配）")
    platform_id: int | None = Field(None, description="渠道平台 ID")
    status: str = Field(Conversation.STATUS_AI_PROCESSING, description="会话初始状态")
    handling_type: str = Field(Conversation.HANDLING_AI_ONLY, description="处理方式（ai_only/human）")
    tags: list[str] = Field(default_factory=list, description="标签列表")
    idle_timeout_seconds: int = Field(1800, description="空闲超时时间（秒）")

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in CONVERSATION_STATUSES:
            raise ValueError("会话状态不合法")
        return value

    @field_validator("handling_type")
    @classmethod
    def validate_handling_type(cls, value: str) -> str:
        if value not in HANDLING_TYPES:
            raise ValueError("处理类型不合法")
        return value


class ConversationUpdate(CamelModel):
    """更新会话"""

    status: str | None = Field(None, description="会话状态")
    employee_id: int | None = Field(None, description="分配坐席 ID")
    handling_type: str | None = Field(None, description="处理方式")
    is_transferred: bool | None = Field(None, description="是否已转接")
    transfer_reason: str | None = Field(None, description="转接原因")
    tags: list[str] | None = Field(None, description="标签列表")
    idle_timeout_seconds: int | None = Field(None, description="空闲超时时间（秒）")

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in CONVERSATION_STATUSES:
            raise ValueError("会话状态不合法")
        return value

    @field_validator("handling_type")
    @classmethod
    def validate_handling_type(cls, value: str | None) -> str | None:
        if value is not None and value not in HANDLING_TYPES:
            raise ValueError("处理类型不合法")
        return value


class ConversationResponse(CamelModel):
    """会话响应"""

    id: int = Field(description="会话 ID")
    tenant_id: int = Field(description="租户 ID")
    contact_id: int = Field(description="客户联系人 ID")
    contact_name: str | None = Field(None, description="客户名称")
    contact_avatar_url: str | None = Field(None, description="客户头像 URL")
    employee_id: int | None = Field(None, description="当前处理坐席 ID")
    employee_name: str | None = Field(None, description="当前处理坐席名称")
    platform_id: int | None = Field(None, description="渠道平台 ID")
    status: str = Field(description="会话状态")
    handling_type: str = Field(description="处理方式（ai_only/human）")
    is_transferred: bool = Field(description="是否已转接")
    transfer_reason: str | None = Field(None, description="转接原因")
    tags: list[str] = Field(default_factory=list, description="标签列表")
    last_message_at: datetime | None = Field(None, description="最后消息时间")
    last_message_preview: str | None = Field(None, description="最后消息预览")
    unread_count: int = Field(0, description="未读数")
    idle_timeout_seconds: int = Field(description="空闲超时时间（秒）")
    created_at: datetime = Field(description="创建时间")
    closed_at: datetime | None = Field(None, description="关闭时间")

    @field_serializer("id", "tenant_id", "contact_id", "employee_id", "platform_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)


class ConversationListResponse(CamelModel):
    """会话列表响应"""

    items: list[ConversationResponse] = Field(description="会话列表")
    total: int = Field(description="总数")
    page: int = Field(description="当前页码")
    page_size: int = Field(description="每页条数")


class MessageCreate(CamelModel):
    """创建消息"""

    sender_type: str = Field(Conversation.SENDER_AGENT, description="发送者类型")
    content_type: str = Field("text", description="消息内容类型（text/image/voice/file/card/event）")
    content: str = Field(description="消息内容")
    metadata: dict | None = Field(None, description="消息扩展元数据")
    reply_to_id: int | None = Field(None, description="回复目标消息 ID")

    @field_validator("sender_type")
    @classmethod
    def validate_sender_type(cls, value: str) -> str:
        value = value.upper()
        if value not in SENDER_TYPES:
            raise ValueError("发送者类型不合法")
        return value

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, value: str) -> str:
        if value not in CONTENT_TYPES:
            raise ValueError("消息类型不合法")
        return value

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("消息内容不能为空")
        return value


class MessageResponse(CamelModel):
    """消息响应"""

    id: int = Field(description="消息 ID")
    conversation_id: int = Field(description="所属会话 ID")
    sender_type: str = Field(description="发送者类型")
    content_type: str = Field(description="消息内容类型")
    content: str | None = Field(None, description="消息内容")
    metadata: dict | None = Field(None, description="消息扩展元数据")
    reply_to_id: int | None = Field(None, description="回复目标消息 ID")
    is_read: bool = Field(description="是否已读")
    is_recalled: bool = Field(False, description="是否已撤回")
    created_at: datetime = Field(description="发送时间")

    @field_serializer("id", "conversation_id", "reply_to_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)


class MessageListResponse(CamelModel):
    """消息列表响应"""

    items: list[MessageResponse] = Field(description="消息列表")
    total: int = Field(description="总数")
    page: int = Field(description="当前页码")
    page_size: int = Field(description="每页条数")
