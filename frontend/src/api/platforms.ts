import request from './request'

export interface PlatformResponse {
  id: string
  tenantId: string
  type: string
  name: string | null
  config: Record<string, any>
  webhookUrl: string | null
  isActive: boolean
  createdAt: string
}

export interface PlatformListResponse {
  items: PlatformResponse[]
  total: number
}

export interface PlatformPayload {
  type?: string
  name?: string | null
  config?: Record<string, any>
  webhookUrl?: string | null
  isActive?: boolean
}

export function getPlatforms() {
  return request.get<PlatformListResponse>('/platforms').then((res) => res.data)
}

export function createPlatform(data: PlatformPayload) {
  return request.post<PlatformResponse>('/platforms', data).then((res) => res.data)
}

export function updatePlatform(id: string | number, data: PlatformPayload) {
  return request.put<PlatformResponse>(`/platforms/${id}`, data).then((res) => res.data)
}

export function deletePlatform(id: string | number) {
  return request.delete(`/platforms/${id}`)
}
