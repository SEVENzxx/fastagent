<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  status: string
}>()

const statusMeta = computed(() => {
  const map: Record<string, { label: string; color: string }> = {
    online: { label: '在线', color: '#16a34a' },
    away: { label: '离开', color: '#f59e0b' },
    busy: { label: '忙碌', color: '#ef4444' },
    offline: { label: '离线', color: '#94a3b8' },
  }
  return map[props.status] ?? map.offline
})
</script>

<template>
  <span class="status">
    <i :style="{ backgroundColor: statusMeta.color }" />
    {{ statusMeta.label }}
  </span>
</template>

<style scoped>
.status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text);
}

.status i {
  width: 8px;
  height: 8px;
  border-radius: 999px;
}
</style>
