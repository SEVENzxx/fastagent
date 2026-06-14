<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { ProductResponse } from '@/api/products'
import * as knowledgeApi from '@/api/knowledge'
import type { KnowledgeDocResponse } from '@/api/knowledge'

const props = defineProps<{
  visible: boolean
  product: ProductResponse | null
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  'uploaded': []
}>()

const doc = ref<KnowledgeDocResponse | null>(null)
const loading = ref(false)
const uploading = ref(false)
const showReplaceUpload = ref(false)
let statusPollTimer: ReturnType<typeof setTimeout> | null = null

function stopStatusPolling() {
  if (statusPollTimer) {
    clearTimeout(statusPollTimer)
    statusPollTimer = null
  }
}

function scheduleStatusPolling() {
  stopStatusPolling()
  if (!props.visible || doc.value?.status !== 'processing') return
  statusPollTimer = setTimeout(() => {
    loadDoc(true)
  }, 3000)
}

async function loadDoc(silent = false) {
  if (!props.product) return
  if (!silent) loading.value = true
  try {
    const result = await knowledgeApi.listKnowledgeDocs(0, 1, props.product.id)
    doc.value = result.items.length > 0 ? result.items[0] : null
  } catch {
    doc.value = null
  } finally {
    if (!silent) loading.value = false
    scheduleStatusPolling()
  }
}

async function handleUpload(file: File) {
  if (!props.product) return
  uploading.value = true
  try {
    await knowledgeApi.uploadKnowledgeDoc(file, props.product.id)
    ElMessage.success('知识文档已上传，正在后台处理')
    showReplaceUpload.value = false
    emit('uploaded')
    await loadDoc()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '上传失败')
  } finally {
    uploading.value = false
  }
}

async function handleViewChunks() {
  if (!doc.value) return
  try {
    const detail = await knowledgeApi.getKnowledgeDoc(doc.value.id)
    const chunks = detail.chunks || []
    const text = chunks.length
      ? chunks.map((c) => `[分块 ${c.chunkIndex}] ${c.content}`).join('\n\n')
      : '暂无分块内容'
    await ElMessageBox.alert(text, doc.value.title, {
      confirmButtonText: '关闭',
      customClass: 'knowledge-detail-msgbox',
    })
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '获取详情失败')
  }
}

function statusTag(status: string) {
  switch (status) {
    case 'ready': return { type: 'success' as const, text: '就绪' }
    case 'processing': return { type: 'warning' as const, text: '处理中' }
    case 'failed': return { type: 'danger' as const, text: '失败' }
    default: return { type: 'info' as const, text: status }
  }
}

watch(() => props.visible, (v) => {
  if (v) {
    showReplaceUpload.value = false
    loadDoc()
  } else {
    stopStatusPolling()
  }
})

onBeforeUnmount(stopStatusPolling)

</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="product ? `知识文档 — ${product.name}` : '知识文档'"
    width="560px"
    top="8vh"
    @update:model-value="(v: boolean) => emit('update:visible', v)"
  >
    <!-- Loading -->
    <div v-if="loading" style="text-align:center;padding:40px;color:var(--text-muted)">加载中...</div>

    <!-- 已有文档 -->
    <template v-else-if="doc && !showReplaceUpload">
      <div class="doc-info">
        <div class="doc-row">
          <span class="doc-label">文件名</span>
          <span class="doc-value">{{ doc.title }}</span>
        </div>
        <div class="doc-row">
          <span class="doc-label">类型</span>
          <el-tag size="small" type="info">{{ doc.fileType?.toUpperCase() }}</el-tag>
        </div>
        <div class="doc-row">
          <span class="doc-label">状态</span>
          <el-tag size="small" :type="statusTag(doc.status).type">{{ statusTag(doc.status).text }}</el-tag>
        </div>
        <div class="doc-row">
          <span class="doc-label">分块数</span>
          <span class="doc-value">{{ doc.chunkCount }}</span>
        </div>
        <div class="doc-row">
          <span class="doc-label">上传时间</span>
          <span class="doc-value">{{ doc.createdAt }}</span>
        </div>
        <div v-if="doc.errorMessage" class="doc-row">
          <span class="doc-label">错误信息</span>
          <span class="doc-value" style="color:var(--danger)">{{ doc.errorMessage }}</span>
        </div>
      </div>

      <div style="display:flex;gap:8px;margin-top:16px">
        <el-button v-if="doc.status === 'ready'" type="primary" plain size="small" @click="handleViewChunks">查看分块内容</el-button>
        <el-button type="warning" plain size="small" @click="showReplaceUpload = true">重新上传</el-button>
      </div>
      <div style="margin-top:8px;font-size:12px;color:var(--text-muted)">重新上传将删除当前文档及其所有分块和向量数据，重新解析上传。</div>
    </template>

    <!-- 上传区域（新增 或 替换） -->
    <template v-else>
      <div v-if="doc" style="margin-bottom:12px;padding:10px 14px;background:var(--warning-soft);border-radius:6px;font-size:13px;color:var(--text)">
        将替换现有文档「<strong>{{ doc.title }}</strong>」— 旧文档的分块和向量数据将被清除。
      </div>
      <el-upload
        :auto-upload="false"
        :show-file-list="true"
        :limit="1"
        accept=".pdf,.docx,.md,.txt,.html"
        drag
        @change="(_file: any, fileList: any[]) => {
          const raw = fileList[fileList.length - 1]?.raw
          if (raw) handleUpload(raw)
        }"
      >
        <div class="upload-placeholder">
          <p style="font-size:36px;margin:0">📄</p>
          <p style="margin:8px 0 0;color:var(--text-muted)">拖拽文件到此处，或点击上传</p>
          <p style="font-size:12px;color:var(--text-muted);margin-top:4px">支持 PDF / DOCX / MD / TXT / HTML</p>
        </div>
      </el-upload>
      <div v-if="uploading" style="text-align:center;margin-top:12px;color:var(--text-muted)">
        正在上传并解析文档...
      </div>
    </template>

    <template #footer>
      <el-button @click="emit('update:visible', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.doc-info {
  display: grid;
  gap: 10px;
}
.doc-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.doc-label {
  font-size: 13px;
  color: var(--text-muted);
  min-width: 64px;
  flex-shrink: 0;
}
.doc-value {
  font-size: 13px;
  color: var(--text);
}
.upload-placeholder {
  padding: 32px 16px;
  text-align: center;
}
</style>

<style>
.knowledge-detail-msgbox {
  max-width: 520px;
}
.knowledge-detail-msgbox .el-message-box__message {
  max-height: 360px;
  overflow-y: auto;
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text);
}
</style>
