import request from './request'

export interface MarketingDocResponse {
  id: string
  title: string
  fileUrl: string
  fileType: string
  questionAssociations: string[] | null
  isActive: boolean
  createdByEmployeeId: string | null
  createdAt: string
  updatedAt: string
}

export interface MarketingDocListResponse {
  items: MarketingDocResponse[]
  total: number
}

export interface MarketingDocCreate {
  title: string
  fileType: string
}

export interface MarketingDocUpdate {
  title?: string
  fileType?: string
  questionAssociations?: string[]
  isActive?: boolean
}

export function listMarketingDocs(skip = 0, limit = 20, isActive?: boolean) {
  return request.get<MarketingDocListResponse>('/marketing', {
    params: { skip, limit, is_active: isActive },
  }).then((res) => res.data)
}

export function createMarketingDoc(data: MarketingDocCreate) {
  return request.post<MarketingDocResponse>('/marketing', data).then((res) => res.data)
}

export function updateMarketingDoc(docId: string, data: MarketingDocUpdate) {
  return request.put<MarketingDocResponse>(`/marketing/${docId}`, data).then((res) => res.data)
}

export function deleteMarketingDoc(docId: string) {
  return request.delete(`/marketing/${docId}`)
}
