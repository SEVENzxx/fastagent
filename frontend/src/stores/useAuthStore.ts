import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as authApi from '@/api/auth'
import type { User } from '@/api/auth'
import { usePermissionStore } from './usePermissionStore'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const token = ref<string | null>(localStorage.getItem('token'))
  const refreshToken = ref<string | null>(localStorage.getItem('refreshToken'))

  const isAuthenticated = computed(() => !!token.value)

  function setAuth(accessToken: string, refreshTokenStr: string) {
    token.value = accessToken
    refreshToken.value = refreshTokenStr
    localStorage.setItem('token', accessToken)
    localStorage.setItem('refreshToken', refreshTokenStr)
  }

  function clearAuth() {
    user.value = null
    token.value = null
    refreshToken.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('refreshToken')
    const permStore = usePermissionStore()
    permStore.clear()
  }

  async function login(email: string, password: string) {
    const res = await authApi.login(email, password)
    setAuth(res.accessToken, res.refreshToken)
    await fetchUser()
  }

  async function register(data: authApi.RegisterParams) {
    const res = await authApi.register(data)
    setAuth(res.accessToken, res.refreshToken)
    await fetchUser()
  }

  async function fetchUser() {
    user.value = await authApi.getMe()
    if (user.value?.permissions) {
      const permStore = usePermissionStore()
      permStore.setCodes(user.value.permissions)
    }
  }

  function logout() {
    clearAuth()
    window.location.href = '/login'
  }

  return {
    user,
    token,
    refreshToken,
    isAuthenticated,
    login,
    register,
    logout,
    fetchUser,
  }
})
