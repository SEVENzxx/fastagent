import request from './request'

export interface OrderItemResponse {
  id: string
  orderId: string
  productId: string | null
  productSnapshot: Record<string, any> | null
  quantity: number
  unitPrice: number
  subtotal: number
  createdAt: string
}

export interface OrderResponse {
  id: string
  tenantId: string
  contactId: string
  conversationId: string | null
  employeeId: string | null
  status: string
  totalAmount: number
  discountAmount: number
  payableAmount: number
  shippingAddress: string | null
  receiverName: string | null
  receiverPhone: string | null
  remark: string | null
  metadata: Record<string, any> | null
  createdByType: string
  createdByEmployeeId: string | null
  confirmedAt: string | null
  shippedAt: string | null
  signedAt: string | null
  cancelledAt: string | null
  createdAt: string
  updatedAt: string
  items: OrderItemResponse[]
  contactName: string | null
}

export interface OrderListResponse {
  items: OrderResponse[]
  total: number
  page: number
  pageSize: number
}

export interface OrderItemCreate {
  productName: string
  quantity: number
}

export interface OrderCreate {
  contactId?: string | number
  conversationId?: string | number
  items: OrderItemCreate[]
  shippingAddress?: string | null
  receiverName?: string | null
  receiverPhone?: string | null
  remark?: string | null
}

export interface OrderUpdate {
  shippingAddress?: string | null
  receiverName?: string | null
  receiverPhone?: string | null
  remark?: string | null
  discountAmount?: number | null
  addItems?: OrderItemCreate[] | null
  removeItemIds?: number[] | null
}

export interface OrderBatchStatusTransition {
  orderIds: Array<string | number>
  status: string
}

export interface BatchStatusResponse {
  succeeded: string[]
  failed: string[]
}

export const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  pending_customer_confirm: '待客户确认',
  customer_confirmed: '客户已确认',
  agent_confirmed: '坐席已确认',
  shipped: '已发货',
  signed: '已签收',
  cancelled: '已取消',
}

export const STATUS_COLORS: Record<string, string> = {
  draft: 'info',
  pending_customer_confirm: 'warning',
  customer_confirmed: 'success',
  agent_confirmed: '',
  shipped: 'primary',
  signed: 'success',
  cancelled: 'danger',
}

export function getOrders(params: {
  contactId?: string | number | null
  status?: string | null
  employeeId?: string | number | null
  page?: number
  pageSize?: number
} = {}) {
  return request
    .get<OrderListResponse>('/orders', {
      params: {
        contact_id: params.contactId || undefined,
        status: params.status || undefined,
        employee_id: params.employeeId || undefined,
        page: params.page,
        page_size: params.pageSize,
      },
    })
    .then((res) => res.data)
}

export function getOrder(id: string | number) {
  return request.get<OrderResponse>(`/orders/${id}`).then((res) => res.data)
}

export function createOrder(data: OrderCreate) {
  return request.post<OrderResponse>('/orders', data).then((res) => res.data)
}

export function updateOrder(id: string | number, data: OrderUpdate) {
  return request.put<OrderResponse>(`/orders/${id}`, data).then((res) => res.data)
}

export function transitionOrderStatus(id: string | number, status: string) {
  return request
    .patch<OrderResponse>(`/orders/${id}/status`, { status })
    .then((res) => res.data)
}

export function batchTransitionStatus(data: OrderBatchStatusTransition) {
  return request
    .patch<BatchStatusResponse>('/orders/batch/status', data)
    .then((res) => res.data)
}

export function cancelOrder(id: string | number) {
  return request.delete(`/orders/${id}`)
}
