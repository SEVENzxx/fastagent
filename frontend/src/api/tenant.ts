import request from './request'

/** 单个属性定义 */
export interface AttributeDef {
  key: string
  label: string
  type: 'boolean' | 'number' | 'enum' | 'text'
  aliases: string[]
  description: string
  queryPath: string[]
  queryStrategy: 'jsonb_bool' | 'jsonb_number' | 'jsonb_text' | 'jsonb_equals' | 'jsonb_contains'
  unit?: string | null
  allowedValues?: string[]
}

/** 租户属性模板响应 */
export interface TenantTemplateResponse {
  attributes: AttributeDef[]
}

/** 更新租户属性模板请求 */
export interface TenantTemplateUpdate {
  attributes: AttributeDef[]
}

export function getTenantTemplate() {
  return request.get<TenantTemplateResponse>('/tenant/template').then((res) => res.data)
}

export function updateTenantTemplate(data: TenantTemplateUpdate) {
  return request
    .put<TenantTemplateResponse>('/tenant/template', data)
    .then((res) => res.data)
}
