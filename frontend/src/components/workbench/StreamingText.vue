<script setup lang="ts">
defineProps<{
  content: string
}>()
</script>

<template>
  <div class="streaming-row">
    <div class="streaming-bubble">
      <div class="streaming-meta">
        <span>AI</span>
        <span class="dot" />
        <span>正在输入</span>
      </div>
      <p>{{ content || '正在整理回复...' }}</p>
    </div>
  </div>
</template>

<style scoped>
.streaming-row {
  display: flex;
  margin-bottom: 12px;
}

.streaming-bubble {
  max-width: min(68%, 560px);
  margin-left: 48px;
  padding: 10px 12px;
  border: 1px solid #cfe2ff;
  border-radius: 8px;
  background: #f7fbff;
}

.streaming-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
  color: #2563eb;
  font-size: 11px;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: #2563eb;
  animation: pulse 1s ease-in-out infinite;
}

p {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.55;
}

@keyframes pulse {
  0%, 100% {
    opacity: 0.35;
  }
  50% {
    opacity: 1;
  }
}
</style>
