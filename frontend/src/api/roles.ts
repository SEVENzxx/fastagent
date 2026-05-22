import request from './request'

export interface PermissionResponse {
  id: string
  code: string
  name: string
  description: string | null
}

export interface PermissionGroupedResponse {
  module: string
  permissions: PermissionResponse[]
}

export interface RoleResponse {
  id: string
  tenantId: string
  name: string
  description: string | null
  createdAt: string
  updatedAt: string
}

export interface RoleDetailResponse extends RoleResponse {
  permissions: PermissionResponse[]
}

export interface RoleCreate {
  name: string
  description: string | null
  permissionIds: string[]
}

export interface RoleUpdate {
  name?: string
  description?: string | null
}

export interface RolePermissionAssign {
  permissionIds: string[]
}

export function getPermissions() {
  return request.get<PermissionGroupedResponse[]>('/permissions').then(r => r.data)
}

export function getRoles() {
  return request.get<RoleDetailResponse[]>('/roles').then(r => r.data)
}

export function getRole(id: string) {
  return request.get<RoleDetailResponse>(`/roles/${id}`).then(r => r.data)
}

export function createRole(data: RoleCreate) {
  return request.post<RoleDetailResponse>('/roles', {
    name: data.name,
    description: data.description,
    permissionIds: data.permissionIds,
  }).then(r => r.data)
}

export function updateRole(id: string, data: RoleUpdate) {
  return request.put<RoleDetailResponse>(`/roles/${id}`, data).then(r => r.data)
}

export function deleteRole(id: string) {
  return request.delete(`/roles/${id}`)
}

export function getRolePermissions(id: string) {
  return request.get<PermissionResponse[]>(`/roles/${id}/permissions`).then(r => r.data)
}

export function setRolePermissions(id: string, data: RolePermissionAssign) {
  return request.put<RoleDetailResponse>(`/roles/${id}/permissions`, data).then(r => r.data)
}
