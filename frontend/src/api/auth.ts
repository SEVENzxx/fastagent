import request from './request'

export interface LoginParams {
  email: string
  password: string
}

export interface RegisterParams {
  companyName: string
  email: string
  password: string
  displayName?: string
}

export interface TokenResponse {
  accessToken: string
  refreshToken: string
  tokenType: string
  expiresIn: number
}

export interface User {
  id: number
  email: string
  displayName: string | null
  isSuperuser: boolean
  tenantId: number
  createdAt: string
  permissions: string[]
}

export function login(email: string, password: string) {
  return request.post<TokenResponse>('/auth/login', { email, password }).then((res) => res.data)
}

export function register(params: RegisterParams) {
  return request.post<TokenResponse>('/auth/register', params).then((res) => res.data)
}

export function refreshToken(token: string) {
  return request.post<TokenResponse>('/auth/refresh', { refreshToken: token }).then((res) => res.data)
}

export function getMe() {
  return request.get<User>('/auth/me').then((res) => res.data)
}
