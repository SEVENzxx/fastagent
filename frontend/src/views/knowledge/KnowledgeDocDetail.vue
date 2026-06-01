<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import * as knowledgeApi from '@/api/knowledge'
import type { KnowledgeDocResponse, KnowledgeChunkResponse } from '@/api/knowledge'

const route = useRoute()
const router = useRouter()
const doc = ref<KnowledgeDocResponse | null>(null)
const chunks = ref<KnowledgeChunkResponse[]>([])
const loading = ref(true)

async function loadData() {
  loading.value = true
  try {
    const docId = route.params.id as string
    const result = await knowledgeApi.getKnowledgeDoc(docId)
    doc.value = result
    chunks.value = result.chunks || []
  } catch {
    ElMessage.error('加载文档详情失败')
  } finally {
    loading.value = false
  }
}

function goBack() {
  router.push('/knowledge')
}

const statusLabels: Record<string, string> = {
  processing: '处理中',
  ready: '就绪',
  failed: '失败',
}

onMounted(loadData)
</script>

<template>
  <div class="knowledge-doc-detail">
    <div class="page-header">
      <el-button :icon="ArrowLeft" text @click="goBack">返回列表</el-button>
    </div>

    <div v-if="doc" v-loading="loading">
      <h2>{{ doc.title }}</h2>
      <el-descriptions :column="3" border style="margin-top: 16px">
        <el-descriptions-item label="文档类型">{{ doc.fileType }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ statusLabels[doc.status] || doc.status }}</el-descriptions-item>
        <el-descriptions-item label="分块数">{{ doc.chunkCount }}</el-descriptions-item>
        <el-descriptions-item v-if="doc.errorMessage" label="错误信息" :span="3">
          <span style="color: red">{{ doc.errorMessage }}</span>
        </el-descriptions-item>
      </el-descriptions>

      <h3 style="margin-top: 24px">分块列表 ({{ chunks.length }})</h3>
      <div v-if="chunks.length === 0" style="color: #909399; padding: 24px">
        暂无分块数据
      </div>
      <div v-for="chunk in chunks" :key="chunk.id" class="chunk-card">
        <div class="chunk-header">
          <el-tag size="small" type="info">#{{ chunk.chunkIndex }}</el-tag>
          <span class="chunk-meta">Tokens: {{ chunk.tokenCount }}</span>
          <span v-if="chunk.metadata?.heading" class="chunk-meta">
            章节: {{ chunk.metadata.heading }}
          </span>
        </div>
        <div class="chunk-content">{{ chunk.content }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.knowledge-doc-detail { padding: 24px; max-width: 960px; }
.chunk-card {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 12px 16px;
  margin: 12px 0;
}
.chunk-header { display: flex; gap: 12px; align-items: center; margin-bottom: 8px; }
.chunk-meta { color: #909399; font-size: 13px; }
.chunk-content { white-space: pre-wrap; font-size: 14px; line-height: 1.7; }
</style>
