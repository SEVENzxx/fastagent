import request from './request'

export interface TenantTemplateResponse {
  templateJson: string[]
}

export function getTenantTemplate() {
  return request.get<TenantTemplateResponse>('/tenant/template').then((res) => res.data)
}

export function updateTenantTemplate(templateJson: string[]) {
  return request
    .put<TenantTemplateResponse>('/tenant/template', { templateJson })
    .then((res) => res.data)
}
