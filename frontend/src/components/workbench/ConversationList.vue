<script setup lang="ts">
import type { ConversationResponse } from '@/api/conversations'

defineProps<{
  conversations: ConversationResponse[]
  activeId: string | null
  loading?: boolean
}>()

const emit = defineEmits<{
  select: [conversation: ConversationResponse]
}>()

function statusText(status: string) {
  const map: Record<string, string> = {
    ai_processing: 'AI处理中',
    pending_human: '待人工',
    human_processing: '人工处理中',
    closed: '已关闭',
    followup: '跟进中',
  }
  return map[status] ?? status
}

function statusType(status: string) {
  if (status === 'pending_human') return 'warning'
  if (status === 'human_processing') return 'success'
  if (status === 'closed') return 'info'
  return 'primary'
}
</script>

<template>
  <div class="conversation-list" v-loading="loading">
    <button
      v-for="conversation in conversations"
      :key="conversation.id"
      type="button"
      class="conversation-item"
      :class="{ active: conversation.id === activeId }"
      @click="emit('select', conversation)"
    >
      <el-avatar :size="36" :src="conversation.contactAvatarUrl || undefined">
        {{ (conversation.contactName || '?').slice(0, 1) }}
      </el-avatar>
      <span class="item-main">
        <span class="item-title">
          <strong>{{ conversation.contactName || '未知客户' }}</strong>
          <el-badge v-if="conversation.unreadCount" :value="conversation.unreadCount" />
        </span>
        <small>{{ conversation.lastMessagePreview || '暂无消息' }}</small>
        <span class="item-foot">
          <el-tag size="small" :type="statusType(conversation.status)" effect="light">
            {{ statusText(conversation.status) }}
          </el-tag>
          <em>{{ conversation.employeeName || '未分配' }}</em>
        </span>
      </span>
    </button>
    <el-empty v-if="!loading && !conversations.length" description="暂无会话" />
  </div>
</template>

<style scoped>
.conversation-list {
  display: grid;
  align-content: start;
  gap: 8px;
}

.conversation-item {
  width: 100%;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px;
  text-align: left;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
}

.conversation-item:hover,
.conversation-item.active {
  border-color: var(--border);
  background: var(--surface-soft);
}

.item-main {
  min-width: 0;
  flex: 1;
  display: grid;
  gap: 5px;
}

.item-title,
.item-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

strong,
small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

small,
em {
  color: var(--text-muted);
  font-size: 12px;
  font-style: normal;
}
</style>
