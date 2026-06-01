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
    contact_id: int
    employee_id: int | None = None
    platform_id: int | None = None
    status: str = Conversation.STATUS_AI_PROCESSING
    handling_type: str = Conversation.HANDLING_AI_ONLY
    tags: list[str] = Field(default_factory=list)
    idle_timeout_seconds: int = 1800

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
    status: str | None = None
    employee_id: int | None = None
    handling_type: str | None = None
    is_transferred: bool | None = None
    transfer_reason: str | None = None
    tags: list[str] | None = None
    idle_timeout_seconds: int | None = None

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
    id: int
    tenant_id: int
    contact_id: int
    contact_name: str | None = None
    contact_avatar_url: str | None = None
    employee_id: int | None = None
    employee_name: str | None = None
    platform_id: int | None = None
    status: str
    handling_type: str
    is_transferred: bool
    transfer_reason: str | None = None
    tags: list[str] = Field(default_factory=list)
    last_message_at: datetime | None = None
    last_message_preview: str | None = None
    unread_count: int = 0
    idle_timeout_seconds: int
    created_at: datetime
    closed_at: datetime | None = None

    @field_serializer("id", "tenant_id", "contact_id", "employee_id", "platform_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)


class ConversationListResponse(CamelModel):
    items: list[ConversationResponse]
    total: int
    page: int
    page_size: int


class MessageCreate(CamelModel):
    sender_type: str = Conversation.SENDER_AGENT
    content_type: str = "text"
    content: str
    metadata: dict | None = None
    reply_to_id: int | None = None

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
    id: int
    conversation_id: int
    sender_type: str
    content_type: str
    content: str | None = None
    metadata: dict | None = None
    reply_to_id: int | None = None
    is_read: bool
    is_recalled: bool = False
    created_at: datetime

    @field_serializer("id", "conversation_id", "reply_to_id")
    def serialize_bigint(self, value: int | None) -> str | None:
        if value is None:
            return None
        return str(value)


class MessageListResponse(CamelModel):
    items: list[MessageResponse]
    total: int
    page: int
    page_size: int
