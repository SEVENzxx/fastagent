<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import * as platformsApi from '@/api/platforms'
import type { PlatformResponse } from '@/api/platforms'
import WebhookUrlDisplay from '@/components/channel/WebhookUrlDisplay.vue'

const platform = ref<PlatformResponse | null>(null)
const loading = ref(false)
const saving = ref(false)
const form = reactive({
  name: '企业微信',
  corpid: '',
  corpsecret: '',
  token: '',
  encodingAesKey: '',
  agentid: '',
  isActive: true,
})

const webhookUrl = computed(() => {
  if (!platform.value) return ''
  const base = window.location.origin
  return `${base}/api/v1/webhooks/wecom/${platform.value.id}`
})

function fillForm(item: PlatformResponse) {
  platform.value = item
  form.name = item.name || '企业微信'
  form.corpid = item.config?.corpid || ''
  form.corpsecret = item.config?.corpsecret || ''
  form.token = item.config?.token || ''
  form.encodingAesKey = item.config?.encoding_aes_key || ''
  form.agentid = item.config?.agentid || ''
  form.isActive = item.isActive
}

async function loadPlatform() {
  loading.value = true
  try {
    const result = await platformsApi.getPlatforms()
    const wecom = result.items.find((item) => item.type === 'wecom') ?? null
    if (wecom) fillForm(wecom)
  } finally {
    loading.value = false
  }
}

function payload() {
  return {
    type: 'wecom',
    name: form.name,
    webhookUrl: webhookUrl.value || null,
    isActive: form.isActive,
    config: {
      corpid: form.corpid,
      corpsecret: form.corpsecret,
      token: form.token,
      encoding_aes_key: form.encodingAesKey,
      agentid: form.agentid,
    },
  }
}

async function savePlatform() {
  saving.value = true
  try {
    const saved = platform.value
      ? await platformsApi.updatePlatform(platform.value.id, payload())
      : await platformsApi.createPlatform(payload())
    fillForm(saved)
    if (!saved.webhookUrl && webhookUrl.value) {
      const updated = await platformsApi.updatePlatform(saved.id, { webhookUrl: webhookUrl.value })
      fillForm(updated)
    }
    ElMessage.success('企业微信配置已保存')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(loadPlatform)
</script>

<template>
  <div class="wechat-page" v-loading="loading">
    <header class="page-header">
      <div>
        <p>渠道配置</p>
        <h2>企业微信接入</h2>
      </div>
      <el-tag :type="platform?.isActive ? 'success' : 'info'" effect="light">
        {{ platform?.isActive ? '已启用' : '未配置' }}
      </el-tag>
    </header>

    <section class="settings-grid">
      <div class="config-panel">
        <h3>基础配置</h3>
        <el-form label-position="top">
          <el-form-item label="渠道别名">
            <el-input v-model="form.name" />
          </el-form-item>
          <el-form-item label="CorpID">
            <el-input v-model="form.corpid" placeholder="企业微信后台的企业 ID" />
          </el-form-item>
          <el-form-item label="CorpSecret">
            <el-input v-model="form.corpsecret" type="password" show-password placeholder="自建应用 Secret" />
          </el-form-item>
          <el-form-item label="AgentID">
            <el-input v-model="form.agentid" placeholder="自建应用 AgentID，可后续真实出站使用" />
          </el-form-item>
          <el-form-item label="Token">
            <el-input v-model="form.token" placeholder="回调 Token" />
          </el-form-item>
          <el-form-item label="EncodingAESKey">
            <el-input v-model="form.encodingAesKey" placeholder="回调加解密 Key" />
          </el-form-item>
          <el-form-item>
            <el-switch v-model="form.isActive" active-text="启用渠道" />
          </el-form-item>
        </el-form>
        <el-button type="primary" :loading="saving" @click="savePlatform">保存配置</el-button>
      </div>

      <div class="webhook-panel">
        <h3>Webhook</h3>
        <WebhookUrlDisplay :url="webhookUrl" />
        <div class="hint">
          在企业微信后台回调地址配置中填入上方 URL，即可接收客户消息。
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.wechat-page {
  display: grid;
  gap: 18px;
}

.page-header {
  min-height: 86px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 24px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
}

.page-header p {
  margin: 0 0 6px;
  color: var(--text-muted);
  font-size: 13px;
}

.page-header h2,
.config-panel h3,
.webhook-panel h3 {
  margin: 0;
  color: var(--text-strong);
}

.settings-grid {
  display: grid;
  grid-template-columns: minmax(360px, 1fr) minmax(360px, 0.9fr);
  gap: 18px;
}

.config-panel,
.webhook-panel {
  display: grid;
  align-content: start;
  gap: 14px;
  padding: 20px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
}

.hint {
  color: var(--text-muted);
  font-size: 13px;
  line-height: 1.6;
}

@media (max-width: 980px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
}
</style>
