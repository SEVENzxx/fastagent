import request from './request'

export interface TodoResponse {
  id: string
  tenantId: string
  conversationId: string
  contactId: string
  content: string
  keywords: string[]
  status: string
  dueAt: string | null
  completedAt: string | null
  createdByType: string
  createdAt: string
  updatedAt: string
}

export interface Contact360Response {
  contactId: string
  name: string
  phone: string | null
  address: string | null
  tags: string[]
  assignedEmployeeName: string | null
  salesContext: {
    stage: string
    pricingLevel: string
    followupState: string
    nextFollowupAt: string | null
    lastInteractionAt: string | null
    summary: string | null
  }
  memories: Array<{ id: string; memoryType: string; key: string; value: string; source: string; updatedAt: string }>
  productContexts: Array<{ id: string; productId: string; productName: string | null; stage: string; quotedPrice: number | null; priceLevel: number; orderId: string | null }>
  orders: Array<{ id: string; status: string; payableAmount: number; createdAt: string }>
  todos: TodoResponse[]
}

export function getContact360(contactId: string | number) {
  return request.get<Contact360Response>(`/sales/contacts/${contactId}/360`).then((res) => res.data)
}

export function createTodo(data: { conversationId: string | number; content: string; dueAt?: string | null }) {
  return request.post<TodoResponse>('/sales/todos', data).then((res) => res.data)
}

export function updateTodo(id: string | number, data: { status?: string; content?: string; dueAt?: string | null }) {
  return request.patch<TodoResponse>(`/sales/todos/${id}`, data).then((res) => res.data)
}
