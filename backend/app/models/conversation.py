"""会话与消息模型"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.utils.id_generator import generate_id


class Conversation(Base):
    """客户会话"""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=generate_id, comment="主键"
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, comment="租户ID"
    )
    contact_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("contacts.id"), nullable=False, comment="客户ID"
    )
    employee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id"), nullable=True, comment="分配坐席ID"
    )
    platform_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("platforms.id"), nullable=True, comment="来源渠道ID"
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="ai_processing",
        server_default="ai_processing",
        comment="会话状态",
    )
    handling_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="ai_only",
        server_default="ai_only",
        comment="处理类型",
    )
    is_transferred: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"), comment="是否已转人工"
    )
    transfer_reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="转接原因")
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True, comment="会话标签")
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最后消息时间"
    )
    idle_timeout_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1800, server_default="1800", comment="空闲超时秒数"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="关闭时间"
    )

    contact: Mapped["Contact"] = relationship("Contact")
    employee: Mapped["Employee | None"] = relationship("Employee")
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_conv_tenant_status", "tenant_id", "status"),
        Index("idx_conv_contact", "contact_id"),
        Index("idx_conv_employee", "employee_id"),
        Index("idx_conv_last_msg", last_message_at.desc()),
        {"comment": "会话表"},
    )


class Message(Base):
    """会话消息"""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, default=generate_id, comment="主键"
    )
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id"), nullable=False, comment="会话ID"
    )
    sender_type: Mapped[str] = mapped_column(String(10), nullable=False, comment="发送者类型")
    content_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="text", server_default="text", comment="内容类型"
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="消息内容")
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True, comment="消息元数据")
    reply_to_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("messages.id"), nullable=True, comment="回复消息ID"
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"), comment="是否已读"
    )
    is_recalled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"), comment="是否已撤回"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")
    reply_to: Mapped["Message | None"] = relationship("Message", remote_side=[id])

    __table_args__ = (
        Index("idx_msg_conversation", "conversation_id", "created_at"),
        Index("idx_msg_created_at", "created_at"),
        {"comment": "消息表"},
    )
