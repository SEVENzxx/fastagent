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

/** 租户属性模板响应（按分类） */
export interface TenantTemplateResponse {
  categoryId: string
  categoryName: string
  attributes: AttributeDef[]
}

/** 更新租户属性模板请求 */
export interface TenantTemplateUpdate {
  categoryId: string
  attributes: AttributeDef[]
}

/** 分类属性配置选项 */
export interface CategoryAttrOption {
  categoryId: string
  categoryName: string
  attrCount: number
}

export function getTenantTemplate(categoryId?: string) {
  const params: Record<string, string> = {}
  if (categoryId !== undefined) params.category_id = categoryId
  return request.get<TenantTemplateResponse>('/tenant/template', { params }).then((res) => res.data)
}

export function updateTenantTemplate(data: TenantTemplateUpdate) {
  return request
    .put<TenantTemplateResponse>('/tenant/template', data)
    .then((res) => res.data)
}

export function getTemplateCategories() {
  return request.get<CategoryAttrOption[]>('/tenant/template/categories').then((res) => res.data)
}
