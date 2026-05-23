import request from './request'

export interface ConversationResponse {
  id: string
  tenantId: string
  contactId: string
  contactName: string | null
  contactAvatarUrl: string | null
  employeeId: string | null
  employeeName: string | null
  platformId: string | null
  status: string
  handlingType: string
  isTransferred: boolean
  transferReason: string | null
  tags: string[]
  lastMessageAt: string | null
  lastMessagePreview: string | null
  unreadCount: number
  idleTimeoutSeconds: number
  createdAt: string
  closedAt: string | null
}

export interface ConversationListResponse {
  items: ConversationResponse[]
  total: number
  page: number
  pageSize: number
}

export interface ConversationCreate {
  contactId: string | number
  employeeId?: string | number | null
  platformId?: string | number | null
  status?: string
  handlingType?: string
  tags?: string[]
  idleTimeoutSeconds?: number
}

export interface ConversationUpdate {
  status?: string | null
  employeeId?: string | number | null
  handlingType?: string | null
  isTransferred?: boolean | null
  transferReason?: string | null
  tags?: string[] | null
  idleTimeoutSeconds?: number | null
}

export interface MessageResponse {
  id: string
  conversationId: string
  senderType: string
  contentType: string
  content: string | null
  metadata: Record<string, any> | null
  replyToId: string | null
  isRead: boolean
  isRecalled: boolean
  createdAt: string
}

export interface MessageListResponse {
  items: MessageResponse[]
  total: number
  page: number
  pageSize: number
}

export interface MessageCreate {
  senderType?: string
  contentType?: string
  content: string
  metadata?: Record<string, any> | null
  replyToId?: string | number | null
}

export interface ConversationSearchParams {
  status?: string | null
  keyword?: string
  employeeId?: string | number | null
  page?: number
  pageSize?: number
}

function toQuery(params: ConversationSearchParams) {
  return {
    status: params.status,
    keyword: params.keyword,
    employee_id: params.employeeId,
    page: params.page,
    page_size: params.pageSize,
  }
}

export function getConversations(params: ConversationSearchParams = {}) {
  return request
    .get<ConversationListResponse>('/conversations', { params: toQuery(params) })
    .then((res) => res.data)
}

export function createConversation(data: ConversationCreate) {
  // “打开会话”接口：后端会保证同一联系人只返回一个会话。
  // 如果该联系人原会话已关闭，后端会按本次传入的 status/handlingType 重新接起旧会话。
  return request.post<ConversationResponse>('/conversations', data).then((res) => res.data)
}

export function getConversation(id: string | number) {
  return request.get<ConversationResponse>(`/conversations/${id}`).then((res) => res.data)
}

export function updateConversation(id: string | number, data: ConversationUpdate) {
  // 普通状态/坐席更新接口。已关闭会话不能通过这里重新打开，避免状态下拉误操作。
  return request.put<ConversationResponse>(`/conversations/${id}`, data).then((res) => res.data)
}

export function getMessages(conversationId: string | number, page = 1, pageSize = 100) {
  return request
    .get<MessageListResponse>(`/conversations/${conversationId}/messages`, {
      params: { page, page_size: pageSize },
    })
    .then((res) => res.data)
}

export function sendMessage(conversationId: string | number, data: MessageCreate) {
  // HTTP 发送兜底：页面优先走 WebSocket，WS 不可用时会调用这里完成同样的消息写入。
  return request
    .post<MessageResponse>(`/conversations/${conversationId}/messages`, data)
    .then((res) => res.data)
}

export function recallMessage(conversationId: string | number, messageId: string | number) {
  return request
    .put<MessageResponse>(`/conversations/${conversationId}/messages/${messageId}/recall`)
    .then((res) => res.data)
}

export function markMessagesRead(conversationId: string | number) {
  return request.put<{ updated: number }>(`/conversations/${conversationId}/messages/read`)
}
