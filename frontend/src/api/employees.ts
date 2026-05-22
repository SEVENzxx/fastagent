import request from './request'
import type { RoleResponse } from './roles'

export interface EmployeeDetailResponse {
  id: string
  tenantId: string
  email: string
  displayName: string | null
  avatarUrl: string | null
  phone: string | null
  isSuperuser: boolean
  onlineStatus: string
  skills: string[] | null
  maxConcurrentChats: number
  lastLoginAt: string | null
  createdAt: string
  roles: RoleResponse[]
}

export interface EmployeeCreate {
  email: string
  password: string
  displayName?: string | null
  avatarUrl?: string | null
  phone?: string | null
  skills?: string[] | null
  maxConcurrentChats?: number
}

export interface EmployeeUpdate {
  displayName?: string | null
  avatarUrl?: string | null
  phone?: string | null
  skills?: string[] | null
  maxConcurrentChats?: number
  isSuperuser?: boolean
}

export interface EmployeeRoleAssign {
  roleIds: string[]
}

export interface ProfileResponse {
  id: string
  email: string
  displayName: string | null
  avatarUrl: string | null
  phone: string | null
  skills: string[] | null
}

export interface ProfileUpdate {
  displayName?: string | null
  avatarUrl?: string | null
  phone?: string | null
  skills?: string[] | null
}

export interface PasswordChange {
  currentPassword: string
  newPassword: string
}

export function getEmployees() {
  return request.get<EmployeeDetailResponse[]>('/employees').then((res) => res.data)
}

export function createEmployee(data: EmployeeCreate) {
  return request.post<EmployeeDetailResponse>('/employees', data).then((res) => res.data)
}

export function updateEmployee(id: string, data: EmployeeUpdate) {
  return request.put<EmployeeDetailResponse>(`/employees/${id}`, data).then((res) => res.data)
}

export function deleteEmployee(id: string) {
  return request.delete(`/employees/${id}`)
}

export function getEmployeeRoles(id: string) {
  return request.get<RoleResponse[]>(`/employees/${id}/roles`).then((res) => res.data)
}

export function setEmployeeRoles(id: string, data: EmployeeRoleAssign) {
  return request.put<RoleResponse[]>(`/employees/${id}/roles`, data).then((res) => res.data)
}

export function getProfile() {
  return request.get<ProfileResponse>('/employees/me/profile').then((res) => res.data)
}

export function updateProfile(data: ProfileUpdate) {
  return request.put<ProfileResponse>('/employees/me/profile', data).then((res) => res.data)
}

export function changePassword(data: PasswordChange) {
  return request.put('/employees/me/password', data)
}
