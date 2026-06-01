import request from './request'

export interface ImageResponse {
  id: string
  filename: string
  fileUrl: string
  fileSize: number
  mimeType: string
  width: number | null
  height: number | null
  productId: string | null
  tags: string[] | null
  createdByEmployeeId: string | null
  createdAt: string
  updatedAt: string
}

export interface ImageListResponse {
  items: ImageResponse[]
  total: number
}

export interface ImageUpdate {
  tags?: string[]
  productId?: number
}

export function listImages(skip = 0, limit = 20, productId?: number) {
  return request.get<ImageListResponse>('/images', {
    params: { skip, limit, product_id: productId },
  }).then((res) => res.data)
}

export function uploadImage(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return request.post<ImageResponse>('/images/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then((res) => res.data)
}

export function updateImage(imageId: string, data: ImageUpdate) {
  return request.put<ImageResponse>(`/images/${imageId}`, data).then((res) => res.data)
}

export function deleteImage(imageId: string) {
  return request.delete(`/images/${imageId}`)
}
