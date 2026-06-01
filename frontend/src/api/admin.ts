import request from './request'

export interface AdminDashboard {
  tenantCount: number
  activeTenantCount: number
  planCount: number
  llmConfigCount: number
  conversationCount: number
  orderCount: number
}

export interface Plan {
  id: string
  name: string
  description: string | null
  features: Record<string, any>
  limits: Record<string, any>
  priceMonthly: number | null
  priceYearly: number | null
  isActive: boolean
}

export interface LLMConfig {
  id: string
  name: string
  provider: string
  apiBase: string | null
  model: string
  pricing: Record<string, any>
  purpose: string
  isActive: boolean
  hasApiKey: boolean
}

export interface Tenant {
  id: string
  name: string
  slug: string
  planId: string | null
  planName: string | null
  planExpiresAt: string | null
  customPrompt: string | null
  selectedLlmConfigId: string | null
  selectedLlmConfigName: string | null
  isActive: boolean
}

export interface PagedResponse<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
}

export interface AdminConversation {
  id: string
  tenantId: string
  tenantName: string
  contactName: string | null
  employeeName: string | null
  status: string
  handlingType: string
  isTransferred: boolean
  lastMessageAt: string | null
  lastMessagePreview: string | null
  createdAt: string
}

export interface AdminMessage {
  id: string
  conversationId: string
  senderType: string
  contentType: string
  content: string | null
  isRecalled: boolean
  createdAt: string
}

export interface AdminOrder {
  id: string
  tenantId: string
  tenantName: string
  contactName: string | null
  status: string
  payableAmount: number
  createdByType: string
  createdAt: string
}

export interface AdminKnowledgeDoc {
  id: string
  tenantId: string
  tenantName: string
  title: string
  fileType: string
  status: string
  chunkCount: number
  errorMessage: string | null
  createdAt: string
}

export const getDashboard = () => request.get<AdminDashboard>('/admin/dashboard').then((res) => res.data)
export const listPlans = () => request.get<Plan[]>('/admin/plans').then((res) => res.data)
export const createPlan = (data: Record<string, any>) => request.post<Plan>('/admin/plans', data).then((res) => res.data)
export const updatePlan = (id: string, data: Record<string, any>) => request.patch<Plan>(`/admin/plans/${id}`, data).then((res) => res.data)
export const listLLMConfigs = () => request.get<LLMConfig[]>('/admin/llm-configs').then((res) => res.data)
export const createLLMConfig = (data: Record<string, any>) => request.post<LLMConfig>('/admin/llm-configs', data).then((res) => res.data)
export const updateLLMConfig = (id: string, data: Record<string, any>) => request.patch<LLMConfig>(`/admin/llm-configs/${id}`, data).then((res) => res.data)
export const listTenants = () => request.get<Tenant[]>('/admin/tenants').then((res) => res.data)
export const createTenant = (data: Record<string, any>) => request.post<Tenant>('/admin/tenants', data).then((res) => res.data)
export const updateTenant = (id: string, data: Record<string, any>) => request.patch<Tenant>(`/admin/tenants/${id}`, data).then((res) => res.data)
export const listBusinessConversations = (params: Record<string, any>) => request.get<PagedResponse<AdminConversation>>('/admin/business/conversations', { params }).then((res) => res.data)
export const listBusinessMessages = (conversationId: string, params: Record<string, any> = {}) => request.get<PagedResponse<AdminMessage>>(`/admin/business/conversations/${conversationId}/messages`, { params }).then((res) => res.data)
export const listBusinessOrders = (params: Record<string, any>) => request.get<PagedResponse<AdminOrder>>('/admin/business/orders', { params }).then((res) => res.data)
export const listBusinessKnowledgeDocs = (params: Record<string, any>) => request.get<PagedResponse<AdminKnowledgeDoc>>('/admin/business/knowledge-docs', { params }).then((res) => res.data)

// ── 系统运维 ──

export interface SystemSettingItem {
  key: string
  value: string
  description?: string | null
}

export interface DbHealth {
  activeConnections: number
  maxConnections: number
  dbSizeMb: number
  uptimeHours: number
  slowQueries24h: number
  indexHitRate: number
}

export interface BackupRecord {
  id: string
  name: string
  sizeBytes: number
  sizeMb: number
  type: string
  status: string
  errorMessage?: string | null
  createdAt: string
}

export const getSystemSettings = () =>
  request.get<{ settings: SystemSettingItem[] }>('/admin/system/settings').then((res) => res.data)

export const updateSystemSettings = (data: { settings: Record<string, string> }) =>
  request.put('/admin/system/settings', data).then((res) => res.data)

export const getDbHealth = () =>
  request.get<DbHealth>('/admin/system/db-health').then((res) => res.data)

export const listBackups = () =>
  request.get<BackupRecord[]>('/admin/system/backups').then((res) => res.data)

export const createBackup = (type: string = 'full') =>
  request.post(`/admin/system/backups?type=${type}`).then((res) => res.data)

export const restoreBackup = (id: string) =>
  request.post(`/admin/system/backups/${id}/restore`).then((res) => res.data)

export const deleteBackup = (id: string) =>
  request.delete(`/admin/system/backups/${id}`).then((res) => res.data)
