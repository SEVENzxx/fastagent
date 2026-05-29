<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as conversationsApi from '@/api/conversations'
import * as contactsApi from '@/api/contacts'
import * as employeesApi from '@/api/employees'
import * as ordersApi from '@/api/orders'
import type { ConversationResponse, MessageResponse } from '@/api/conversations'
import type { ContactResponse } from '@/api/contacts'
import type { EmployeeDetailResponse } from '@/api/employees'
import ConversationList from '@/components/workbench/ConversationList.vue'
import ChatWindow from '@/components/workbench/ChatWindow.vue'
import { useWebSocket } from '@/composables/useWebSocket'

const conversations = ref<ConversationResponse[]>([])
const contacts = ref<ContactResponse[]>([])
const employees = ref<EmployeeDetailResponse[]>([])
const messages = ref<MessageResponse[]>([])
const activeConversation = ref<ConversationResponse | null>(null)
const loading = ref(false)
const keyword = ref('')
const statusFilter = ref<string | null>(null)
const createContactId = ref<string | null>(null)
const createEmployeeId = ref<string | null>(null)
const createHandlingType = ref('ai_only')
const aiTyping = ref(false)
const streamingText = ref('')
let refreshTimer: number | undefined

const activeId = computed(() => activeConversation.value?.id ?? null)
const selectedCreateContact = computed(
  () => contacts.value.find((contact) => contact.id === createContactId.value) ?? null,
)

const ws = useWebSocket(
  () => activeConversation.value?.id ?? null,
  (payload) => {
    if (payload.type === 'message.created' && payload.message) {
      const message = payload.message as MessageResponse
      if (!messages.value.some((item) => item.id === message.id)) {
        messages.value.push(message)
      }
      if (message.senderType === 'AI') {
        aiTyping.value = false
        streamingText.value = ''
      }
      loadConversations()
    }
    if (payload.type === 'ai.typing') {
      aiTyping.value = Boolean(payload.typing)
      if (!aiTyping.value) streamingText.value = ''
    }
    if (payload.type === 'ai.message.chunk') {
      aiTyping.value = true
      streamingText.value += String(payload.content || '')
    }
    if (payload.type === 'message.recalled' && payload.message) {
      const message = payload.message as MessageResponse
      const index = messages.value.findIndex((item) => item.id === message.id)
      if (index >= 0) messages.value[index] = message
    }
    if (payload.type === 'conversation.updated') {
      loadConversations()
    }
  },
)

async function loadConversations() {
  loading.value = true
  try {
    const result = await conversationsApi.getConversations({
      keyword: keyword.value || undefined,
      status: statusFilter.value || undefined,
      page: 1,
      pageSize: 50,
    })
    conversations.value = result.items
    if (activeConversation.value) {
      const fresh = result.items.find((item) => item.id === activeConversation.value?.id)
      if (fresh) activeConversation.value = fresh
    } else if (result.items.length) {
      await selectConversation(result.items[0])
    }
  } finally {
    loading.value = false
  }
}

async function loadContacts() {
  const result = await contactsApi.getContacts({ page: 1, pageSize: 100 })
  contacts.value = result.items
}

async function loadEmployees() {
  try {
    employees.value = await employeesApi.getEmployees()
  } catch {
    employees.value = []
  }
}

async function loadMessages(conversationId: string) {
  const result = await conversationsApi.getMessages(conversationId, 1, 200)
  messages.value = result.items
  await conversationsApi.markMessagesRead(conversationId)
}

async function selectConversation(conversation: ConversationResponse) {
  activeConversation.value = conversation
  messages.value = []
  aiTyping.value = false
  streamingText.value = ''
  ws.close()
  await loadMessages(conversation.id)
  ws.connect()
}

async function sendMessage(content: string) {
  if (!activeConversation.value) return
  // 优先通过 WebSocket 发送，保证两个浏览器打开同一会话时能即时收到。
  // 如果连接还没建立或断开，则降级到 HTTP 接口发送。
  const sentViaSocket = ws.send({
    type: 'message.send',
    senderType: 'AGENT',
    contentType: 'text',
    content,
  })
  if (!sentViaSocket) {
    const message = await conversationsApi.sendMessage(activeConversation.value.id, {
      senderType: 'AGENT',
      contentType: 'text',
      content,
    })
    messages.value.push(message)
  }
}

async function updateStatus(status: string) {
  if (!activeConversation.value) return
  // 状态下拉只处理正常流转；关闭后的会话要通过右侧“打开会话”恢复，避免误触复活。
  if (activeConversation.value.status === 'closed' && status !== 'closed') {
    ElMessage.warning('已关闭的会话不能重新修改状态')
    return
  }
  const handlingType =
    status === 'ai_processing'
      ? 'ai_only'
      : status === 'human_processing' || status === 'pending_human'
        ? 'human'
        : undefined
  activeConversation.value = await conversationsApi.updateConversation(activeConversation.value.id, {
    status,
    handlingType,
  })
  await loadConversations()
}

async function createConversation() {
  if (!createContactId.value) {
    ElMessage.warning('请先选择联系人')
    return
  }
  try {
    // 这里的“打开会话”不一定会新建：后端会复用该联系人的已有会话。
    // 如果已有会话是已关闭，会按当前选择的处理方式恢复，并保留历史消息继续聊。
    const status = createHandlingType.value === 'ai_only' ? 'ai_processing' : 'pending_human'
    const conversation = await conversationsApi.createConversation({
      contactId: createContactId.value,
      employeeId: createEmployeeId.value || selectedCreateContact.value?.assignedEmployeeId || null,
      status,
      handlingType: createHandlingType.value,
    })
    ElMessage.success('会话已打开')
    createContactId.value = null
    createEmployeeId.value = null
    createHandlingType.value = 'ai_only'
    await loadConversations()
    await selectConversation(conversation)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '创建会话失败')
  }
}

async function handleOrderStatusChange(orderId: string, toStatus: string) {
  try {
    await ordersApi.transitionOrderStatus(orderId, toStatus)
    ElMessage.success('订单状态已更新')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '操作失败')
  }
}

watch([keyword, statusFilter], () => {
  loadConversations()
})

onMounted(async () => {
  await Promise.all([loadContacts(), loadEmployees(), loadConversations()])
  // 事件驱动：WebSocket 推送 message.created / conversation.updated 时自动刷新列表
  // 30s 兜底轮询：覆盖「未选中会话时期 WebSocket 断开」导致的漏更新（如 webhook 新建会话）
  refreshTimer = window.setInterval(() => {
    loadConversations()
  }, 30000)
})

onBeforeUnmount(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
  ws.close()
})
</script>

<template>
  <div class="workbench">
    <aside class="left-panel">
      <div class="panel-header">
        <h2>会话</h2>
        <el-select v-model="statusFilter" placeholder="全部状态" clearable size="small" class="status-filter">
          <el-option label="AI处理中" value="ai_processing" />
          <el-option label="待人工" value="pending_human" />
          <el-option label="人工处理中" value="human_processing" />
          <el-option label="跟进中" value="followup" />
          <el-option label="已关闭" value="closed" />
        </el-select>
      </div>
      <el-input
        v-model="keyword"
        placeholder="搜索客户"
        clearable
        class="search-input"
      />
      <ConversationList
        :conversations="conversations"
        :active-id="activeId"
        :loading="loading"
        @select="selectConversation"
      />
    </aside>

    <section class="center-panel">
      <ChatWindow
        :conversation="activeConversation"
        :messages="messages"
        :connected="ws.connected.value"
        :ai-typing="aiTyping"
        :streaming-text="streamingText"
        @send="sendMessage"
        @status-change="updateStatus"
        @order-status-change="handleOrderStatusChange"
      />
    </section>

    <aside class="right-panel">
      <section class="side-section">
        <h3>打开会话</h3>
        <el-select
          v-model="createContactId"
          filterable
          placeholder="选择联系人"
          style="width: 100%"
        >
          <el-option
            v-for="contact in contacts"
            :key="contact.id"
            :label="contact.name"
            :value="contact.id"
          />
        </el-select>
        <p v-if="selectedCreateContact" class="hint-line">
          联系人归属坐席：{{ selectedCreateContact.assignedEmployeeName || '未分配' }}
        </p>
        <el-select
          v-model="createEmployeeId"
          filterable
          clearable
          placeholder="默认使用联系人归属坐席"
          style="width: 100%"
        >
          <el-option
            v-for="employee in employees"
            :key="employee.id"
            :label="employee.displayName || employee.email"
            :value="employee.id"
          />
        </el-select>
        <el-select v-model="createHandlingType" style="width: 100%">
          <el-option label="AI 自动处理" value="ai_only" />
          <el-option label="人工处理" value="human" />
          <el-option label="AI 协作人工" value="collaboration" />
        </el-select>
        <el-button type="primary" style="width: 100%" @click="createConversation">
          打开会话
        </el-button>
      </section>

      <section class="side-section">
        <h3>当前客户</h3>
        <template v-if="activeConversation">
          <p class="side-title">{{ activeConversation.contactName }}</p>
          <p>坐席：{{ activeConversation.employeeName || '未分配' }}</p>
          <p>处理方式：{{ activeConversation.handlingType }}</p>
          <div class="tag-list">
            <el-tag v-for="tag in activeConversation.tags" :key="tag" size="small">
              {{ tag }}
            </el-tag>
          </div>
        </template>
        <el-empty v-else description="未选择会话" />
      </section>
    </aside>
  </div>
</template>

<style scoped>
.workbench {
  height: calc(100vh - 128px);
  min-height: 620px;
  display: flex;
  gap: 0;
  overflow: hidden;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.left-panel,
.right-panel {
  width: 310px;
  min-width: 280px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
  overflow: auto;
}

.left-panel {
  border-right: 1px solid var(--border);
}

.right-panel {
  width: 280px;
  border-left: 1px solid var(--border);
}

.center-panel {
  flex: 1;
  min-width: 0;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.panel-header h2 {
  color: var(--text-strong);
  font-size: 20px;
  line-height: 1;
  white-space: nowrap;
  flex: 0 0 auto;
}

.status-filter {
  width: 150px;
  flex: 0 0 150px;
}

.search-input {
  flex: 0 0 auto;
}

.side-section {
  display: grid;
  gap: 12px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
}

.side-section h3 {
  color: var(--text-strong);
  font-size: 15px;
}

.side-section p {
  margin: 0;
  color: var(--text);
  font-size: 13px;
}

.hint-line {
  color: var(--text-muted) !important;
  font-size: 12px !important;
}

.side-title {
  font-weight: 700;
  color: var(--text-strong) !important;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

@media (max-width: 980px) {
  .workbench {
    height: auto;
    min-height: 0;
    flex-direction: column;
  }

  .left-panel,
  .right-panel {
    width: 100%;
    min-width: 0;
    border: 0;
  }

  .center-panel {
    min-height: 560px;
    border-top: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
  }
}
</style>
