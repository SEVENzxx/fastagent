<script setup lang="ts">
import { usePermissionStore } from '@/stores/usePermissionStore'

const props = defineProps<{
  permission?: string
  anyPermission?: string[]
  allPermissions?: string[]
}>()

const permStore = usePermissionStore()

const allowed = (): boolean => {
  if (props.allPermissions?.length) {
    return permStore.hasAllPermissions(...props.allPermissions)
  }
  if (props.anyPermission?.length) {
    return permStore.hasAnyPermission(...props.anyPermission)
  }
  if (props.permission) {
    return permStore.hasPermission(props.permission)
  }
  return true
}
</script>

<template>
  <slot v-if="allowed()" />
</template>
