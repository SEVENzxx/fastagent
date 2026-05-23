import request from './request'

export interface ProductResponse {
  id: string
  tenantId: string
  categoryId: string | null
  name: string
  sku: string | null
  description: string | null
  price: number | null
  floorPrice: number | null
  stock: number
  isSample: boolean
  salesTemplateId: string | null
  specs: Record<string, any> | null
  isActive: boolean
  createdAt: string
  updatedAt: string
  categoryName: string | null
}

export interface ProductListResponse {
  items: ProductResponse[]
  total: number
  page: number
  pageSize: number
}

export interface ProductCreate {
  name: string
  categoryId?: string | number | null
  sku?: string | null
  description?: string | null
  price?: number | null
  floorPrice?: number | null
  stock?: number
  isSample?: boolean
  salesTemplateId?: string | number | null
  specs?: Record<string, any> | null
  isActive?: boolean
}

export interface ProductUpdate {
  name?: string | null
  categoryId?: string | number | null
  sku?: string | null
  description?: string | null
  price?: number | null
  floorPrice?: number | null
  stock?: number | null
  isSample?: boolean | null
  salesTemplateId?: string | number | null
  specs?: Record<string, any> | null
  isActive?: boolean | null
}

export interface ProductSearchParams {
  keyword?: string
  categoryId?: string | number | null
  isActive?: boolean | null
  isSample?: boolean | null
  minPrice?: number | null
  maxPrice?: number | null
  page?: number
  pageSize?: number
}

export interface ProductImportError {
  row: number
  field: string | null
  message: string
}

export interface ProductImportResponse {
  success: boolean
  totalRows: number
  createdCount: number
  errors: ProductImportError[]
}

function toSearchQuery(params: ProductSearchParams) {
  return {
    keyword: params.keyword,
    category_id: params.categoryId,
    is_active: params.isActive,
    is_sample: params.isSample,
    min_price: params.minPrice,
    max_price: params.maxPrice,
    page: params.page,
    page_size: params.pageSize,
  }
}

export function searchProducts(params: ProductSearchParams = {}) {
  return request
    .get<ProductListResponse>('/products/search', { params: toSearchQuery(params) })
    .then((res) => res.data)
}

export function getProducts(page = 1, pageSize = 20) {
  return request
    .get<ProductListResponse>('/products', { params: { page, page_size: pageSize } })
    .then((res) => res.data)
}

export function getProduct(id: string | number) {
  return request.get<ProductResponse>(`/products/${id}`).then((res) => res.data)
}

export function createProduct(data: ProductCreate) {
  return request.post<ProductResponse>('/products', data).then((res) => res.data)
}

export function updateProduct(id: string | number, data: ProductUpdate) {
  return request.put<ProductResponse>(`/products/${id}`, data).then((res) => res.data)
}

export function deleteProduct(id: string | number) {
  return request.delete(`/products/${id}`)
}

export function importProducts(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return request
    .post<ProductImportResponse>('/products/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((res) => res.data)
}

export function downloadProductImportTemplate() {
  return request
    .get<Blob>('/products/import/template', { responseType: 'blob' })
    .then((res) => res.data)
}
