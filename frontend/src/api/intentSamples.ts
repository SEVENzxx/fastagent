import request from './request'

// ---------------------------------------------------------------------------
// Intent Sample Types
// ---------------------------------------------------------------------------

export interface IntentSampleResponse {
  id: string
  tenantId: string
  scenarioId: string
  label: string
  exampleText: string
  enabled: boolean
  source: string
  schemaVersion: number
  qdrantPointId: string | null
  createdAt: string
  updatedAt: string
}

export interface IntentSampleListResponse {
  items: IntentSampleResponse[]
  total: number
}

export interface IntentSampleCreate {
  scenarioId: string
  label: string
  exampleText: string
  enabled?: boolean
}

export interface IntentSampleUpdate {
  scenarioId?: string
  label?: string
  exampleText?: string
  enabled?: boolean
}

export interface IntentSampleBatchCreate {
  scenarioId: string
  label: string
  examples: string[]
  enabled?: boolean
}

export interface IntentSampleTestHit {
  scenarioId: string
  label: string
  score: number
  exampleText: string
  source: string
  tenantId: number
}

export interface IntentSampleTestSearchResponse {
  query: string
  results: IntentSampleTestHit[]
}

export interface SkillOption {
  value: string
  label: string
}

export interface RiskLevelOption {
  value: string
  label: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

export function listIntentSamples(params?: {
  scenarioId?: string
  enabled?: boolean
  skip?: number
  limit?: number
}) {
  return request.get<IntentSampleListResponse>('/ai/intent-samples', { params }).then((res) => res.data)
}

export function createIntentSample(data: IntentSampleCreate) {
  return request.post<IntentSampleResponse>('/ai/intent-samples', data).then((res) => res.data)
}

export function batchCreateIntentSamples(data: IntentSampleBatchCreate) {
  return request.post<IntentSampleResponse[]>('/ai/intent-samples/batch', data).then((res) => res.data)
}

export function updateIntentSample(sampleId: string, data: IntentSampleUpdate) {
  return request.put<IntentSampleResponse>(`/ai/intent-samples/${sampleId}`, data).then((res) => res.data)
}

export function toggleIntentSampleEnabled(sampleId: string, enabled: boolean) {
  return request.patch<IntentSampleResponse>(`/ai/intent-samples/${sampleId}/enabled`, null, {
    params: { enabled },
  }).then((res) => res.data)
}

export function deleteIntentSample(sampleId: string) {
  return request.delete(`/ai/intent-samples/${sampleId}`)
}

export function testSearchIntentSamples(query: string) {
  return request.post<IntentSampleTestSearchResponse>('/ai/intent-samples/test-search', { query }).then((res) => res.data)
}

export function listSkillOptions() {
  return request.get<SkillOption[]>('/ai/intent-samples/skill-options').then((res) => res.data)
}

export function listRiskLevelOptions() {
  return request.get<RiskLevelOption[]>('/ai/intent-samples/risk-level-options').then((res) => res.data)
}
