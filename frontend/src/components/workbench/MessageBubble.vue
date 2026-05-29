<script setup lang="ts">
import { computed } from 'vue'
import type { MessageResponse } from '@/api/conversations'
import OrderCard from '@/components/orders/OrderCard.vue'

const props = defineProps<{
  message: MessageResponse
}>()

const emit = defineEmits<{
  orderStatusChange: [orderId: string, toStatus: string]
}>()

function senderLabel(senderType: string) {
  const map: Record<string, string> = {
    CUSTOMER: '客户',
    AGENT: '坐席',
    AI: 'AI',
    SYSTEM: '系统',
  }
  return map[senderType] ?? senderType
}

const orderCards = computed(() => {
  const cards = props.message.metadata?.order_cards
  if (!Array.isArray(cards) || !cards.length) return null
  return cards.filter((c: Record<string, any>) => c.order_id)
})
</script>

<template>
  <div class="message-row" :class="message.senderType.toLowerCase()">
    <div class="bubble">
      <div class="meta">
        <span>{{ senderLabel(message.senderType) }}</span>
        <time>{{ new Date(message.createdAt).toLocaleTimeString() }}</time>
      </div>
      <p v-if="message.isRecalled">消息已撤回</p>
      <template v-else>
        <p>{{ message.content }}</p>
        <OrderCard
          v-for="card in orderCards"
          :key="card.order_id"
          :order="card"
          compact
          @status-change="(orderId: any, toStatus: any) => emit('orderStatusChange', orderId, toStatus)"
        />
      </template>
    </div>
  </div>
</template>

<style scoped>
.message-row {
  display: flex;
  margin-bottom: 12px;
}

.message-row.agent {
  justify-content: flex-end;
}

.message-row.ai {
  justify-content: flex-start;
}

.message-row.system {
  justify-content: center;
}

.bubble {
  max-width: min(68%, 560px);
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
}

.agent .bubble {
  background: var(--primary);
  color: #fff;
  border-color: var(--primary);
}

.ai .bubble {
  margin-left: 48px;
  background: #f7fbff;
  border-color: #cfe2ff;
  box-shadow: 0 1px 0 rgba(37, 99, 235, 0.04);
}

.system .bubble {
  max-width: 78%;
  background: var(--surface-soft);
}

.ai .meta {
  color: #2563eb;
  opacity: 1;
}

.meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
  font-size: 11px;
  opacity: 0.75;
}

p {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.55;
}
</style>
