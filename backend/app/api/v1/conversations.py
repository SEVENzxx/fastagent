"""会话与消息 API"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.websocket_manager import manager
from app.database import get_db
from app.dependencies import require_permission, require_tenant_user
from app.models.conversation import Conversation, Message
from app.models.employee import Employee
from app.models.role import PermissionCode
from app.schemas.conversation import (
    ConversationCreate,
    ConversationListResponse,
    ConversationResponse,
    ConversationUpdate,
    MessageCreate,
    MessageListResponse,
    MessageResponse,
)
from app.services import conversation_service, outbound_message_service

router = APIRouter(prefix="/conversations", tags=["会话"])


def _conversation_to_response(conversation: Conversation) -> ConversationResponse:
    """把 ORM 会话对象转换成前端使用的响应结构。

    service 层会临时挂载 _contact_name、_employee_name、_unread_count 等展示字段，
    这里统一做 camelCase schema 输出，避免路由函数里散落字段拼装逻辑。
    """
    return ConversationResponse(
        id=conversation.id,
        tenant_id=conversation.tenant_id,
        contact_id=conversation.contact_id,
        contact_name=getattr(conversation, "_contact_name", None),
        contact_avatar_url=getattr(conversation, "_contact_avatar_url", None),
        employee_id=conversation.employee_id,
        employee_name=getattr(conversation, "_employee_name", None),
        platform_id=conversation.platform_id,
        status=conversation.status,
        handling_type=conversation.handling_type,
        is_transferred=conversation.is_transferred,
        transfer_reason=conversation.transfer_reason,
        tags=conversation.tags or [],
        last_message_at=conversation.last_message_at,
        last_message_preview=getattr(conversation, "_last_message_preview", None),
        unread_count=getattr(conversation, "_unread_count", 0),
        idle_timeout_seconds=conversation.idle_timeout_seconds,
        created_at=conversation.created_at,
        closed_at=conversation.closed_at,
    )


def _message_to_response(message: Message) -> MessageResponse:
    """把消息 ORM 对象转换成 API 响应结构。"""
    return MessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        sender_type=message.sender_type,
        content_type=message.content_type,
        content=message.content,
        metadata=message.metadata_ or {},
        reply_to_id=message.reply_to_id,
        is_read=message.is_read,
        is_recalled=message.is_recalled,
        created_at=message.created_at,
    )


async def _broadcast_message(message: Message) -> None:
    """向当前会话频道广播一条新消息。

    HTTP 发消息和 WebSocket 发消息都会落库，落库后统一推送 message.created，
    前端收到后可以即时把消息追加到聊天窗口。
    """
    await manager.publish(
        message.conversation_id,
        {
            "type": "message.created",
            "message": _message_to_response(message).model_dump(mode="json", by_alias=True),
        },
    )


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    status_filter: str | None = Query(default=None, alias="status"),
    keyword: str = Query(default=""),
    employee_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.VIEW_ASSIGNED_CHATS)),
):
    """获取会话列表。

    支持按状态、客户关键词、坐席筛选，并返回分页结果。
    列表项会附带客户名、坐席名、未读数和最后一条消息预览，供左侧会话列表直接展示。
    """
    items, total = await conversation_service.list_conversations(
        db,
        current_user.tenant_id,
        status=status_filter,
        keyword=keyword,
        employee_id=employee_id,
        page=page,
        page_size=page_size,
    )
    return ConversationListResponse(
        items=[_conversation_to_response(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_CONVERSATIONS)),
):
    """打开客户会话。

    这里虽然是 POST，但业务语义不是每次都新建：
    - 同一租户 + 同一联系人已有会话时，直接返回已有会话，避免工作台出现重复客户会话。
    - 如果已有会话已关闭，service 会按本次选择的坐席/处理方式把它恢复为可继续聊天的状态。
    - 只有完全没有历史会话时才真正插入新 conversation。
    """
    try:
        conversation = await conversation_service.create_conversation(
            db,
            current_user.tenant_id,
            body,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _conversation_to_response(conversation)


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.VIEW_ASSIGNED_CHATS)),
):
    """获取单个会话详情。

    只允许访问当前租户内的会话；如果会话不存在或不属于当前租户，返回 404。
    """
    conversation = await conversation_service.get_conversation(
        db,
        conversation_id,
        current_user.tenant_id,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return _conversation_to_response(conversation)


@router.put("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: int,
    body: ConversationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_CONVERSATIONS)),
):
    """更新会话状态、坐席、处理方式等管理字段。

    注意：这个接口用于会话中的状态流转，不负责“重新打开关闭会话”。
    已关闭会话需要通过 POST /conversations 的“打开会话”动作恢复，避免管理员在状态下拉里误操作。
    """
    try:
        conversation = await conversation_service.update_conversation(
            db,
            conversation_id,
            current_user.tenant_id,
            body,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    await manager.publish(
        conversation.id,
        {
            "type": "conversation.updated",
            "conversation": _conversation_to_response(conversation).model_dump(mode="json", by_alias=True),
        },
    )
    return _conversation_to_response(conversation)


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
async def list_messages(
    conversation_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.VIEW_ASSIGNED_CHATS)),
):
    """获取某个会话的消息历史。

    消息按 created_at 正序返回，前端进入会话时用它恢复聊天窗口历史记录。
    """
    try:
        items, total = await conversation_service.list_messages(
            db,
            conversation_id,
            current_user.tenant_id,
            page=page,
            page_size=page_size,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return MessageListResponse(
        items=[_message_to_response(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/{conversation_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def create_message(
    conversation_id: int,
    body: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_tenant_user),
):
    """写入消息并广播给当前会话的在线连接。

    当前接口只负责消息落库和实时推送；真实客户入站与 AI 回复会在后续渠道/AI 管线中接入。
    """
    try:
        conversation, message = await conversation_service.create_message(
            db,
            conversation_id,
            current_user.tenant_id,
            body,
        )
        message = await outbound_message_service.deliver_message(db, conversation, message)
        await _broadcast_message(message)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _message_to_response(message)


@router.put("/{conversation_id}/messages/{message_id}/recall", response_model=MessageResponse)
async def recall_message(
    conversation_id: int,
    message_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_permission(PermissionCode.MANAGE_CONVERSATIONS)),
):
    """撤回指定消息。

    当前实现是软撤回：保留消息记录，但把 is_recalled 标记为 true，并广播 message.recalled。
    """
    try:
        message = await conversation_service.recall_message(
            db,
            message_id,
            conversation_id,
            current_user.tenant_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if message is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    await manager.publish(
        conversation_id,
        {
            "type": "message.recalled",
            "message": _message_to_response(message).model_dump(mode="json", by_alias=True),
        },
    )
    return _message_to_response(message)


@router.put("/{conversation_id}/messages/read")
async def mark_messages_read(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(require_tenant_user),
):
    """把当前会话里的客户消息标记为已读。

    前端打开会话并拉取消息历史后调用，用来清空左侧未读角标。
    """
    try:
        count = await conversation_service.mark_messages_read(
            db,
            conversation_id,
            current_user.tenant_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await manager.publish(conversation_id, {"type": "messages.read", "count": count})
    return {"updated": count}
