import request from './request'

// ---------------------------------------------------------------------------
// Knowledge Doc
// ---------------------------------------------------------------------------

export interface KnowledgeChunkResponse {
  id: string
  docId: string
  chunkIndex: number
  content: string
  tokenCount: number
  metadata: Record<string, any> | null
  createdAt: string
}

export interface KnowledgeDocResponse {
  id: string
  title: string
  fileType: string
  storagePath: string
  status: string
  chunkCount: number
  errorMessage: string | null
  createdByEmployeeId: string | null
  createdAt: string
  updatedAt: string
  chunks?: KnowledgeChunkResponse[]
}

export interface KnowledgeDocListResponse {
  items: KnowledgeDocResponse[]
  total: number
}

export function listKnowledgeDocs(skip = 0, limit = 20) {
  return request.get<KnowledgeDocListResponse>('/knowledge', { params: { skip, limit } }).then((res) => res.data)
}

export function getKnowledgeDoc(docId: string) {
  return request.get<KnowledgeDocResponse>(`/knowledge/${docId}`).then((res) => res.data)
}

export function uploadKnowledgeDoc(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return request.post<KnowledgeDocResponse>('/knowledge/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then((res) => res.data)
}

export function deleteKnowledgeDoc(docId: string) {
  return request.delete(`/knowledge/${docId}`)
}

// ---------------------------------------------------------------------------
// QA Pairs
// ---------------------------------------------------------------------------

export interface QAPairResponse {
  id: string
  question: string
  answer: string
  keywords: string[] | null
  isActive: boolean
  createdByEmployeeId: string | null
  createdAt: string
  updatedAt: string
}

export interface QAPairListResponse {
  items: QAPairResponse[]
  total: number
}

export interface QAPairCreate {
  question: string
  answer: string
  keywords?: string[]
}

export interface QAPairUpdate {
  question?: string
  answer?: string
  keywords?: string[]
  isActive?: boolean
}

export function listQAPairs(skip = 0, limit = 20, isActive?: boolean) {
  return request.get<QAPairListResponse>('/qa-pairs', {
    params: { skip, limit, is_active: isActive },
  }).then((res) => res.data)
}

export function getQAPair(pairId: string) {
  return request.get<QAPairResponse>(`/qa-pairs/${pairId}`).then((res) => res.data)
}

export function createQAPair(data: QAPairCreate) {
  return request.post<QAPairResponse>('/qa-pairs', data).then((res) => res.data)
}

export function updateQAPair(pairId: string, data: QAPairUpdate) {
  return request.put<QAPairResponse>(`/qa-pairs/${pairId}`, data).then((res) => res.data)
}

export function deleteQAPair(pairId: string) {
  return request.delete(`/qa-pairs/${pairId}`)
}

// ---------------------------------------------------------------------------
// Hit Testing
// ---------------------------------------------------------------------------

export interface HitTestRequest {
  query: string
  topK?: number
}

export interface HitTestResponse {
  query: string
  chunks: Array<{
    id: string
    docId: string
    chunkIndex: number
    content: string
    tokenCount: number
    metadata: Record<string, any> | null
    score: number
  }>
  qaMatches: Array<{
    id: string
    question: string
    answer: string
    keywords: string[] | null
    score: number
  }>
}

export function hitTest(data: HitTestRequest) {
  return request.post<HitTestResponse>('/rag/hit-test', data).then((res) => res.data)
}
