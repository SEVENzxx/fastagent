import request from './request'

export interface ContactResponse {
  id: string
  tenantId: string
  name: string
  avatarUrl: string | null
  phone: string | null
  address: string | null
  externalIds: Record<string, any> | null
  tags: string[]
  mergedFrom: string | null
  assignedEmployeeId: string | null
  assignedEmployeeName: string | null
  createdAt: string
  updatedAt: string
}

export interface ContactListResponse {
  items: ContactResponse[]
  total: number
  page: number
  pageSize: number
}

export interface ContactTagAggregate {
  tag: string
  count: number
}

export interface ContactCreate {
  name: string
  avatarUrl?: string | null
  phone?: string | null
  address?: string | null
  externalIds?: Record<string, any> | null
  tags?: string[]
  assignedEmployeeId?: string | number | null
}

export interface ContactUpdate {
  name?: string | null
  avatarUrl?: string | null
  phone?: string | null
  address?: string | null
  externalIds?: Record<string, any> | null
  tags?: string[] | null
  assignedEmployeeId?: string | number | null
}

export interface ContactSearchParams {
  keyword?: string
  tag?: string | null
  assignedEmployeeId?: string | number | null
  page?: number
  pageSize?: number
}

export interface ContactImportError {
  row: number
  field: string | null
  message: string
}

export interface ContactImportResponse {
  success: boolean
  totalRows: number
  createdCount: number
  errors: ContactImportError[]
}

function toQuery(params: ContactSearchParams) {
  return {
    keyword: params.keyword,
    tag: params.tag,
    assigned_employee_id: params.assignedEmployeeId,
    page: params.page,
    page_size: params.pageSize,
  }
}

export function getContacts(params: ContactSearchParams = {}) {
  return request
    .get<ContactListResponse>('/contacts', { params: toQuery(params) })
    .then((res) => res.data)
}

export function getContactTags() {
  return request.get<ContactTagAggregate[]>('/contacts/tags').then((res) => res.data)
}

export function getContact(id: string | number) {
  return request.get<ContactResponse>(`/contacts/${id}`).then((res) => res.data)
}

export function createContact(data: ContactCreate) {
  return request.post<ContactResponse>('/contacts', data).then((res) => res.data)
}

export function updateContact(id: string | number, data: ContactUpdate) {
  return request.put<ContactResponse>(`/contacts/${id}`, data).then((res) => res.data)
}

export function assignContact(id: string | number, assignedEmployeeId: string | number | null) {
  return request
    .put<ContactResponse>(`/contacts/${id}/assign`, { assignedEmployeeId })
    .then((res) => res.data)
}

export function deleteContact(id: string | number) {
  return request.delete(`/contacts/${id}`)
}

export function importContacts(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return request
    .post<ContactImportResponse>('/contacts/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((res) => res.data)
}

export function downloadContactImportTemplate() {
  return request
    .get<Blob>('/contacts/import/template', { responseType: 'blob' })
    .then((res) => res.data)
}
