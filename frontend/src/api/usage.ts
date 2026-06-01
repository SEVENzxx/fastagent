import request from './request'

export interface TenantDashboard {
  conversationCount: number
  messageCount: number
  orderCount: number
  knowledgeDocCount: number
  imageCount: number
  llmTotalTokens: number
  llmTotalCost: number
  planLimits: Record<string, any>
}

export interface UsageLog {
  id: string
  tenantId: string
  source: string
  model: string
  promptTokens: number
  completionTokens: number
  totalTokens: number
  cost: number
  latencyMs: number
  success: boolean
  createdAt: string
}

interface Paged<T> { items: T[]; total: number }

export const getDashboard = () => request.get<TenantDashboard>('/analytics/dashboard').then((res) => res.data)
export const listUsage = (params: Record<string, any> = {}) => request.get<Paged<UsageLog>>('/billing/usage', { params }).then((res) => res.data)
export const listAdminUsage = (params: Record<string, any> = {}) => request.get<Paged<UsageLog>>('/admin/usage', { params }).then((res) => res.data)
