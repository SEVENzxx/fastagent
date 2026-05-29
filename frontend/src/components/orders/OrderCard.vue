<script setup lang="ts">
import type { OrderResponse } from '@/api/orders'
import * as ordersApi from '@/api/orders'

const props = defineProps<{
  order: OrderResponse | Record<string, any>
  compact?: boolean
}>()

const emit = defineEmits<{
  statusChange: [orderId: string, toStatus: string]
}>()

function statusLabel(status: string): string {
  return ordersApi.STATUS_LABELS[status] || status
}

function statusColor(status: string): string {
  return ordersApi.STATUS_COLORS[status] || 'info'
}

function canTransition(order: Record<string, any>, toStatus: string): boolean {
  const transitions: Record<string, string[]> = {
    draft: ['pending_customer_confirm', 'cancelled'],
    pending_customer_confirm: ['customer_confirmed', 'cancelled'],
    customer_confirmed: ['agent_confirmed', 'cancelled'],
    agent_confirmed: ['shipped', 'cancelled'],
    shipped: ['signed'],
    signed: [],
    cancelled: [],
  }
  return (transitions[order.status] || []).includes(toStatus)
}
</script>

<template>
  <div class="order-card" :class="{ compact }">
    <div class="order-card-header">
      <span class="order-id">#{{ order.id || order.order_id }}</span>
      <el-tag :type="statusColor(order.status)" size="small">
        {{ statusLabel(order.status) }}
      </el-tag>
    </div>

    <div v-if="order.items && order.items.length" class="order-items">
      <div v-for="(item, idx) in order.items" :key="idx" class="order-item-line">
        <span class="item-name">{{ item.product_name || item.productSnapshot?.product_name || '-' }}</span>
        <span class="item-qty">x{{ item.quantity }}</span>
        <span class="item-price">
          ¥{{ ((item.subtotal ?? item.unitPrice * item.quantity) || 0).toFixed(2) }}
        </span>
      </div>
    </div>

    <div class="order-card-footer">
      <span class="order-amount">
        <strong>¥{{ ((order.payable_amount ?? order.payableAmount) || 0).toFixed(2) }}</strong>
      </span>

      <div v-if="!compact" class="order-actions">
        <el-button
          v-if="canTransition(order, 'customer_confirmed')"
          size="small"
          type="success"
          @click.stop="emit('statusChange', order.id || order.order_id, 'customer_confirmed')"
        >
          确认
        </el-button>
        <el-button
          v-if="canTransition(order, 'agent_confirmed')"
          size="small"
          type="primary"
          @click.stop="emit('statusChange', order.id || order.order_id, 'agent_confirmed')"
        >
          审核
        </el-button>
        <el-button
          v-if="canTransition(order, 'shipped')"
          size="small"
          type="warning"
          @click.stop="emit('statusChange', order.id || order.order_id, 'shipped')"
        >
          发货
        </el-button>
        <el-button
          v-if="canTransition(order, 'cancelled')"
          size="small"
          type="danger"
          @click.stop="emit('statusChange', order.id || order.order_id, 'cancelled')"
        >
          取消
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.order-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--surface);
  margin: 6px 0;
  max-width: 100%;
}

.order-card.compact {
  padding: 8px 10px;
  border-radius: 6px;
}

.order-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.order-id {
  font-family: monospace;
  font-size: 12px;
  color: var(--el-color-primary);
  font-weight: 600;
}

.order-items {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 8px;
}

.order-item-line {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text);
}

.item-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-qty {
  color: var(--text-muted);
  flex-shrink: 0;
}

.item-price {
  color: var(--text);
  flex-shrink: 0;
  min-width: 70px;
  text-align: right;
}

.order-card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.order-amount strong {
  color: var(--el-color-danger);
  font-size: 14px;
}

.order-actions {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
</style>
