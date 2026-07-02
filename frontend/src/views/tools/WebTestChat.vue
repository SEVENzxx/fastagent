<template>
  <div class="web-test-page">
    <!-- 顶栏 -->
    <header class="web-test-header">
      <div class="header-left">
        <span class="header-icon">🔬</span>
        <span class="header-title">Web 渠道模拟测试</span>
      </div>
      <div class="header-right">
        <span class="header-env">开发环境</span>
        <button v-if="!showForm" class="header-btn" @click="resetSession">切换客户</button>
      </div>
    </header>

    <div class="web-test-body">
      <!-- Step 1: 客户信息表单 -->
      <div v-if="showForm" class="form-container">
        <div class="form-card">
          <h2 class="form-title">客户信息</h2>
          <p class="form-desc">填写客户信息后进入对话，模拟 web 渠道客户与 AI 客服沟通。</p>

          <el-form
            ref="formRef"
            :model="form"
            :rules="formRules"
            label-width="100px"
            size="large"
            @keyup.enter="enterChat"
          >
            <el-form-item label="手机号码" prop="phone">
              <el-input v-model="form.phone" placeholder="请输入手机号码" maxlength="20" />
            </el-form-item>

            <el-form-item label="昵称" prop="nickname">
              <el-input v-model="form.nickname" placeholder="请输入客户昵称" maxlength="50" />
            </el-form-item>

            <el-form-item label="租户 ID" prop="tenantId">
              <el-input-number v-model="form.tenantId" :min="1" placeholder="租户 ID" style="width: 100%" />
            </el-form-item>

            <el-form-item label="备注">
              <el-input
                v-model="form.remark"
                placeholder="选填，备注信息（仅本地展示）"
                maxlength="200"
                clearable
              />
            </el-form-item>

            <el-form-item>
              <el-button type="primary" size="large" style="width: 100%" @click="enterChat">
                进入对话
              </el-button>
            </el-form-item>
          </el-form>
        </div>
      </div>

      <!-- Step 2: 聊天界面 -->
      <div v-else class="chat-container">
        <!-- 会话状态栏 -->
        <div class="chat-status-bar">
          <div class="status-info">
            <el-tag type="success" size="small">已连接</el-tag>
            <span class="status-text">客户：{{ form.nickname }}（{{ form.phone }}）</span>
          </div>
          <div class="status-meta">
            <span class="meta-item">tenant: {{ form.tenantId }}</span>
            <span v-if="contactId" class="meta-item">contact: {{ contactId }}</span>
            <span v-if="conversationId" class="meta-item">conv: {{ conversationId }}</span>
          </div>
        </div>

        <!-- 消息列表 -->
        <div ref="messageListRef" class="message-list">
          <div v-if="messages.length === 0" class="message-empty">
            <p>开始对话吧！输入消息后按 Enter 发送。</p>
          </div>

          <div
            v-for="(msg, idx) in messages"
            :key="idx"
            class="message-row"
            :class="msg.role === 'user' ? 'row-user' : 'row-ai'"
          >
            <div class="message-avatar">
              {{ msg.role === 'user' ? form.nickname.charAt(0) : 'A' }}
            </div>
            <div class="message-content">
              <div class="message-sender">{{ msg.role === 'user' ? form.nickname : 'AI 客服' }}</div>
              <div class="message-bubble" :class="msg.role === 'user' ? 'bubble-user' : 'bubble-ai'">
                <div class="bubble-text">{{ msg.content }}</div>
                <div v-if="msg.resourceTrace" class="bubble-trace">
                  <details>
                    <summary>资源轨迹</summary>
                    <pre>{{ JSON.stringify(msg.resourceTrace, null, 2) }}</pre>
                  </details>
                </div>
              </div>
            </div>
          </div>

          <!-- AI 输入中指示器 -->
          <div v-if="loading" class="message-row row-ai">
            <div class="message-avatar">A</div>
            <div class="message-content">
              <div class="message-sender">AI 客服</div>
              <div class="message-bubble bubble-ai">
                <div class="typing-indicator">
                  <span class="typing-dot"></span>
                  <span class="typing-dot"></span>
                  <span class="typing-dot"></span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 输入区 -->
        <div class="chat-input-area">
          <el-input
            ref="inputRef"
            v-model="inputText"
            :disabled="loading"
            placeholder="输入消息，Enter 发送..."
            @keyup.enter="sendMessage"
          >
            <template #append>
              <el-button :disabled="loading || !inputText.trim()" @click="sendMessage">
                发送
              </el-button>
            </template>
          </el-input>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, nextTick } from 'vue'
import { ElForm, ElMessage } from 'element-plus'

// ── 类型 ──

interface ChatMessage {
  role: 'user' | 'ai'
  content: string
  resourceTrace?: Record<string, unknown>
}

// ── 表单 ──

const formRef = ref<InstanceType<typeof ElForm>>()
const showForm = ref(true)

const form = reactive({
  phone: '',
  nickname: '',
  tenantId: 1,
  remark: '',
})

const formRules = {
  phone: [{ required: true, message: '请输入手机号码', trigger: 'blur' }],
  nickname: [{ required: true, message: '请输入客户昵称', trigger: 'blur' }],
  tenantId: [{ required: true, message: '请选择租户', trigger: 'blur' }],
}

// ── 会话状态 ──

const contactId = ref<number | null>(null)
const conversationId = ref<number | null>(null)

// ── 聊天状态 ──

const messages = ref<ChatMessage[]>([])
const inputText = ref('')
const loading = ref(false)
const messageListRef = ref<HTMLElement>()
const inputRef = ref()

// ── 方法 ──

function scrollToBottom() {
  nextTick(() => {
    const el = messageListRef.value
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  })
}

async function enterChat() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  showForm.value = false
  messages.value = []
  inputText.value = ''
  contactId.value = null
  conversationId.value = null
  ElMessage.success(`已以「${form.nickname}」身份进入对话`)
  nextTick(() => inputRef.value?.focus())
}

function resetSession() {
  showForm.value = true
  messages.value = []
  contactId.value = null
  conversationId.value = null
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || loading.value) return

  inputText.value = ''

  // 添加用户消息
  messages.value.push({ role: 'user', content: text })
  scrollToBottom()

  // 调用 API
  loading.value = true
  try {
    const resp = await fetch('/api/v1/channels/web-test/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tenant_id: form.tenantId,
        phone: form.phone,
        nickname: form.nickname,
        text,
      }),
    })

    if (!resp.ok) {
      const errBody = await resp.json().catch(() => ({}))
      throw new Error(errBody.detail || `请求失败（${resp.status}）`)
    }

    const data = await resp.json()

    // 保存会话/联系人 ID
    contactId.value = data.contact_id
    conversationId.value = data.conversation_id

    // 添加 AI 回复
    const trace = data.resource_trace as Record<string, unknown> | undefined
    messages.value.push({
      role: 'ai',
      content: data.reply,
      resourceTrace: trace,
    })
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : '未知错误'
    ElMessage.error(msg)
    messages.value.push({
      role: 'ai',
      content: `⚠️ ${msg}`,
    })
  } finally {
    loading.value = false
    scrollToBottom()
  }
}
</script>

<style scoped>
/* ── 布局 ── */

.web-test-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #f0f2f5;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

/* ── 顶栏 ── */

.web-test-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
  padding: 0 24px;
  background: #1a1a2e;
  color: #fff;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-icon {
  font-size: 20px;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-env {
  font-size: 12px;
  color: #8bac0f;
  background: rgba(139, 172, 15, 0.15);
  padding: 2px 10px;
  border-radius: 10px;
}

.header-btn {
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #fff;
  padding: 6px 16px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  transition: background 0.2s;
}

.header-btn:hover {
  background: rgba(255, 255, 255, 0.2);
}

/* ── 主体 ── */

.web-test-body {
  flex: 1;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 24px;
  overflow: hidden;
}

/* ── 表单 ── */

.form-container {
  width: 100%;
  max-width: 480px;
  margin-top: 60px;
}

.form-card {
  background: #fff;
  border-radius: 12px;
  padding: 32px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
}

.form-title {
  margin: 0 0 4px;
  font-size: 22px;
  font-weight: 600;
  color: #1a1a2e;
}

.form-desc {
  margin: 0 0 24px;
  font-size: 14px;
  color: #888;
}

/* ── 聊天容器 ── */

.chat-container {
  width: 100%;
  max-width: 720px;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
  overflow: hidden;
}

/* ── 会话状态栏 ── */

.chat-status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid #eee;
  flex-shrink: 0;
}

.status-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-text {
  font-size: 13px;
  color: #333;
}

.status-meta {
  display: flex;
  gap: 12px;
}

.meta-item {
  font-size: 11px;
  color: #999;
  font-family: monospace;
}

/* ── 消息列表 ── */

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.message-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #bbb;
  font-size: 14px;
}

.message-row {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
}

.row-user {
  flex-direction: row-reverse;
}

.row-ai {
  flex-direction: row;
}

.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
}

.row-user .message-avatar {
  background: #1890ff;
  color: #fff;
}

.row-ai .message-avatar {
  background: #52c41a;
  color: #fff;
}

.message-content {
  max-width: 70%;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.message-sender {
  font-size: 12px;
  color: #999;
  padding: 0 4px;
}

.bubble-text {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}

.message-bubble {
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.5;
}

.bubble-user {
  background: #1890ff;
  color: #fff;
  border-bottom-right-radius: 4px;
}

.bubble-ai {
  background: #f0f0f0;
  color: #333;
  border-bottom-left-radius: 4px;
}

.bubble-trace {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(0, 0, 0, 0.08);
}

.bubble-trace details {
  font-size: 11px;
}

.bubble-trace summary {
  cursor: pointer;
  color: #888;
  font-size: 11px;
}

.bubble-trace pre {
  margin: 4px 0 0;
  font-size: 10px;
  color: #666;
  white-space: pre-wrap;
  max-height: 120px;
  overflow-y: auto;
}

/* ── 打字指示器 ── */

.typing-indicator {
  display: flex;
  gap: 4px;
  align-items: center;
  padding: 4px 0;
}

.typing-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #999;
  animation: typing-anim 1.4s infinite ease-in-out;
}

.typing-dot:nth-child(1) { animation-delay: 0s; }
.typing-dot:nth-child(2) { animation-delay: 0.2s; }
.typing-dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes typing-anim {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1); }
}

/* ── 输入区 ── */

.chat-input-area {
  padding: 12px 16px;
  border-top: 1px solid #eee;
  flex-shrink: 0;
}
</style>
