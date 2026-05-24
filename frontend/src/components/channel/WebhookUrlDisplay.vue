<script setup lang="ts">
const props = defineProps<{
  url: string
}>()

async function copyUrl() {
  await navigator.clipboard.writeText(props.url)
}
</script>

<template>
  <div class="webhook-display">
    <div>
      <p class="label">Webhook URL</p>
      <code>{{ url || '保存渠道后生成' }}</code>
    </div>
    <el-button size="small" :disabled="!url" @click="copyUrl">复制</el-button>
  </div>
</template>

<style scoped>
.webhook-display {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-soft);
}

.label {
  margin: 0 0 5px;
  color: var(--text-muted);
  font-size: 12px;
}

code {
  display: block;
  color: var(--text-strong);
  overflow-wrap: anywhere;
}
</style>
