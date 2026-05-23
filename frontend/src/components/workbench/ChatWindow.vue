<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { ConversationResponse, MessageResponse } from '@/api/conversations'
import MessageBubble from './MessageBubble.vue'

const props = defineProps<{
  conversation: ConversationResponse | null
  messages: MessageResponse[]
  connected: boolean
}>()

const emit = defineEmits<{
  send: [content: string]
  statusChange: [status: string]
}>()

const draft = ref('')
const listRef = ref<HTMLElement | null>(null)

watch(
  () => props.messages.length,
  async () => {
    await nextTick()
    if (listRef.value) {
      listRef.value.scrollTop = listRef.value.scrollHeight
    }
  },
)

function handleSend() {
  const content = draft.value.trim()
  if (!content || props.conversation?.status === 'closed') return
  emit('send', content)
  draft.value = ''
}
</script>

<template>
  <div v-if="conversation" class="chat-window">
    <header class="chat-header">
      <div>
        <h3>{{ conversation.contactName || '未知客户' }}</h3>
        <p>{{ conversation.employeeName || '未分配坐席' }}</p>
      </div>
      <div class="header-actions">
        <el-tag :type="connected ? 'success' : 'info'" effect="light">
          {{ connected ? '连接正常' : '未连接' }}
        </el-tag>
        <el-tag v-if="conversation.status === 'closed'" type="info" effect="light">
          已关闭
        </el-tag>
        <el-select
          v-else
          :model-value="conversation.status"
          size="small"
          class="status-select"
          @change="(value: string) => emit('statusChange', value)"
        >
          <el-option label="AI处理中" value="ai_processing" />
          <el-option label="待人工" value="pending_human" />
          <el-option label="人工处理中" value="human_processing" />
          <el-option label="跟进中" value="followup" />
          <el-option label="已关闭" value="closed" />
        </el-select>
      </div>
    </header>

    <main ref="listRef" class="message-list">
      <MessageBubble v-for="message in messages" :key="message.id" :message="message" />
      <el-empty v-if="!messages.length" description="暂无消息" />
    </main>

    <footer class="composer">
      <el-input
        v-model="draft"
        type="textarea"
        :rows="3"
        resize="none"
        placeholder="输入消息，Ctrl + Enter 发送"
        :disabled="conversation.status === 'closed'"
        @keydown.ctrl.enter.prevent="handleSend"
      />
      <el-button
        type="primary"
        :disabled="conversation.status === 'closed'"
        @click="handleSend"
      >
        发送
      </el-button>
    </footer>
  </div>
  <el-empty v-else class="empty-chat" description="请选择左侧会话" />
</template>

<style scoped>
.chat-window {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.chat-header {
  min-height: 68px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
}

.chat-header h3 {
  color: var(--text-strong);
  font-size: 17px;
}

.chat-header p {
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 13px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.status-select {
  width: 140px;
  flex: 0 0 140px;
}

.message-list {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 18px;
  background: var(--app-bg);
}

.composer {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: end;
  gap: 10px;
  padding: 14px;
  border-top: 1px solid var(--border);
}

.empty-chat {
  height: 100%;
  display: grid;
  place-items: center;
}
</style>
