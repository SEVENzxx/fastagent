<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { isAxiosError } from 'axios'
import { Delete, Upload } from '@element-plus/icons-vue'
import * as knowledgeApi from '@/api/knowledge'
import type { KnowledgeDocResponse } from '@/api/knowledge'

const router = useRouter()
const docs = ref<KnowledgeDocResponse[]>([])
const loading = ref(true)
const total = ref(0)
const page = ref(1)
const pageSize = ref(12)
const uploading = ref(false)
const fileInput = ref<HTMLInputElement>()

async function loadData() {
  loading.value = true
  try {
    const skip = (page.value - 1) * pageSize.value
    const result = await knowledgeApi.listKnowledgeDocs(skip, pageSize.value)
    docs.value = result.items
    total.value = result.total
  } catch {
    docs.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

async function handleUpload(file: File) {
  uploading.value = true
  try {
    await knowledgeApi.uploadKnowledgeDoc(file)
    ElMessage.success('文档上传成功，正在处理中...')
    await loadData()
  } catch (error) {
    const message = isAxiosError(error) ? error.response?.data?.detail : null
    ElMessage.error(message || '上传失败')
  } finally {
    uploading.value = false
  }
}

function openFilePicker() {
  if (!uploading.value) {
    fileInput.value?.click()
  }
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) handleUpload(file)
  input.value = ''
}

async function handleDelete(doc: KnowledgeDocResponse) {
  await ElMessageBox.confirm(`确定删除「${doc.title}」及其所有分块吗？`, '删除确认', {
    type: 'warning',
  })
  await knowledgeApi.deleteKnowledgeDoc(doc.id)
  ElMessage.success('已删除')
  await loadData()
}

function viewDetail(doc: KnowledgeDocResponse) {
  router.push(`/knowledge/${doc.id}`)
}

const statusLabels: Record<string, string> = {
  processing: '处理中',
  ready: '就绪',
  failed: '失败',
}
const statusColors: Record<string, string> = {
  processing: 'warning',
  ready: 'success',
  failed: 'danger',
}

onMounted(loadData)
</script>

<template>
  <div class="knowledge-doc-list">
    <div class="page-header">
      <h2>知识文档</h2>
      <el-button type="primary" :icon="Upload" :loading="uploading" @click="openFilePicker">
        {{ uploading ? '上传中...' : '上传文档' }}
      </el-button>
      <input ref="fileInput" type="file" accept=".pdf,.docx,.md,.txt,.html" @change="onFileChange" hidden />
    </div>

    <el-table :data="docs" v-loading="loading" stripe>
      <el-table-column prop="title" label="文档名称" min-width="200" />
      <el-table-column prop="fileType" label="类型" width="80" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusColors[row.status] || 'info'" size="small">
            {{ statusLabels[row.status] || row.status }}
          </el-tag>
          <el-tooltip v-if="row.status === 'failed' && row.errorMessage" :content="row.errorMessage" placement="top">
            <span style="color: red; margin-left: 4px; cursor: help">⚠</span>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column prop="chunkCount" label="分块数" width="80" />
      <el-table-column label="上传时间" width="170">
        <template #default="{ row }">{{ new Date(row.createdAt).toLocaleString() }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button text type="primary" size="small" @click="viewDetail(row)">详情</el-button>
          <el-button text type="danger" size="small" :icon="Delete" @click="handleDelete(row)" />
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination-wrap">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="loadData"
      />
    </div>
  </div>
</template>

<style scoped>
.knowledge-doc-list { padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h2 { margin: 0; }
.pagination-wrap { display: flex; justify-content: center; margin-top: 16px; }
</style>
