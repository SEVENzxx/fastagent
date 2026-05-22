import { defineStore } from 'pinia'
import { ref } from 'vue'

export const usePermissionStore = defineStore('permission', () => {
  const codes = ref<Set<string>>(new Set())
  const loaded = ref(false)

  function setCodes(perms: string[]) {
    codes.value = new Set(perms)
    loaded.value = true
  }

  function hasPermission(code: string): boolean {
    return codes.value.has(code)
  }

  function hasAnyPermission(...requiredCodes: string[]): boolean {
    return requiredCodes.some(c => codes.value.has(c))
  }

  function hasAllPermissions(...requiredCodes: string[]): boolean {
    return requiredCodes.every(c => codes.value.has(c))
  }

  function clear() {
    codes.value = new Set()
    loaded.value = false
  }

  return {
    codes,
    loaded,
    setCodes,
    hasPermission,
    hasAnyPermission,
    hasAllPermissions,
    clear,
  }
})
