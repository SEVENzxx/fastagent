import request from './request'

export interface SensitiveWord {
  id: string
  tenantId: string | null
  word: string
  action: 'block' | 'transfer' | 'warn'
  isActive: boolean
}

export interface Notification {
  id: string
  type: string
  level: string
  title: string
  content: string | null
  resourceType: string | null
  resourceId: string | null
  metadata: Record<string, any>
  isRead: boolean
  createdAt: string
}

export interface AuditLog {
  id: string
  tenantId: string | null
  employeeId: string | null
  action: string
  resourceType: string
  resourceId: string | null
  details: Record<string, any>
  createdAt: string
}

export interface LoginHistory {
  id: string
  email: string
  success: boolean
  failureReason: string | null
  ipAddress: string | null
  createdAt: string
}

interface Paged<T> {
  items: T[]
  total: number
}

export const listSensitiveWords = () => request.get<SensitiveWord[]>('/sensitive-words').then((res) => res.data)
export const createSensitiveWord = (data: Record<string, any>) => request.post<SensitiveWord>('/sensitive-words', data).then((res) => res.data)
export const updateSensitiveWord = (id: string, data: Record<string, any>) => request.patch<SensitiveWord>(`/sensitive-words/${id}`, data).then((res) => res.data)
export const listNotifications = (params: Record<string, any> = {}) => request.get<Paged<Notification>>('/notifications', { params }).then((res) => res.data)
export const markNotificationRead = (id: string) => request.put<Notification>(`/notifications/${id}/read`).then((res) => res.data)
export const listAuditLogs = (params: Record<string, any> = {}) => request.get<Paged<AuditLog>>('/admin/audit-logs', { params }).then((res) => res.data)
export const listLoginHistories = (params: Record<string, any> = {}) => request.get<Paged<LoginHistory>>('/admin/login-histories', { params }).then((res) => res.data)
export const listPlatformSensitiveWords = () => request.get<SensitiveWord[]>('/admin/sensitive-words').then((res) => res.data)
export const createPlatformSensitiveWord = (data: Record<string, any>) => request.post<SensitiveWord>('/admin/sensitive-words', data).then((res) => res.data)
export const updatePlatformSensitiveWord = (id: string, data: Record<string, any>) => request.patch<SensitiveWord>(`/admin/sensitive-words/${id}`, data).then((res) => res.data)
