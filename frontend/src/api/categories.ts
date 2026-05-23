import request from './request'

export interface CategoryResponse {
  id: string
  tenantId: string
  parentId: string | null
  name: string
  sortOrder: number
  createdAt: string
}

export interface CategoryTreeResponse extends CategoryResponse {
  children: CategoryTreeResponse[]
}

export interface CategoryCreate {
  name: string
  parentId?: string | number | null
  sortOrder?: number
}

export interface CategoryUpdate {
  name?: string
  parentId?: string | number | null
  sortOrder?: number
}

export function getCategories() {
  return request.get<CategoryResponse[]>('/categories').then((res) => res.data)
}

export function getCategoryTree() {
  return request.get<CategoryTreeResponse[]>('/categories/tree').then((res) => res.data)
}

export function getCategory(id: string | number) {
  return request.get<CategoryResponse>(`/categories/${id}`).then((res) => res.data)
}

export function createCategory(data: CategoryCreate) {
  return request.post<CategoryResponse>('/categories', data).then((res) => res.data)
}

export function updateCategory(id: string | number, data: CategoryUpdate) {
  return request.put<CategoryResponse>(`/categories/${id}`, data).then((res) => res.data)
}

export function deleteCategory(id: string | number) {
  return request.delete(`/categories/${id}`)
}
