<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import * as knowledgeApi from '@/api/knowledge'
import type { HitTestResponse } from '@/api/knowledge'

const query = ref('')
const loading = ref(false)
const result = ref<HitTestResponse | null>(null)

async function handleSearch() {
  if (!query.value.trim()) return
  loading.value = true
  result.value = null
  try {
    result.value = await knowledgeApi.hitTest({ query: query.value.trim() })
    const total = (result.value.chunks?.length || 0) + (result.value.qaMatches?.length || 0)
    if (total === 0) {
      ElMessage.info('未找到匹配结果')
    }
  } catch {
    ElMessage.error('检索失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="hit-testing">
    <h2>命中测试</h2>
    <p class="subtitle">输入客户可能问的问题，测试 RAG 检索效果</p>

    <div class="search-bar">
      <el-input
        v-model="query"
        placeholder="输入测试问题，例如：你们有什么茶叶？"
        size="large"
        clearable
        @keyup.enter="handleSearch"
      >
        <template #append>
          <el-button type="primary" :icon="Search" :loading="loading" @click="handleSearch">
            检索
          </el-button>
        </template>
      </el-input>
    </div>

    <div v-if="result" class="results">
      <!-- QA Matches -->
      <template v-if="result.qaMatches?.length">
        <h3>问答匹配 ({{ result.qaMatches.length }})</h3>
        <div v-for="qa in result.qaMatches" :key="qa.id" class="result-card qa-card">
          <div class="result-header">
            <el-tag size="small" type="success">QA</el-tag>
            <span class="score">相似度: {{ qa.score }}</span>
          </div>
          <div class="qa-question"><strong>Q:</strong> {{ qa.question }}</div>
          <div class="qa-answer"><strong>A:</strong> {{ qa.answer }}</div>
        </div>
      </template>

      <!-- Chunk Matches -->
      <template v-if="result.chunks?.length">
        <h3>文档匹配 ({{ result.chunks.length }})</h3>
        <div v-for="chunk in result.chunks" :key="chunk.id" class="result-card">
          <div class="result-header">
            <el-tag size="small" type="primary">CHUNK</el-tag>
            <span class="score">相似度: {{ chunk.score }}</span>
            <span v-if="chunk.metadata?.docTitle" class="doc-title">
              来源: {{ chunk.metadata.docTitle }}
            </span>
            <span v-if="chunk.metadata?.heading" class="heading">
              {{ chunk.metadata.heading }}
            </span>
          </div>
          <div class="chunk-content">{{ chunk.content }}</div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.hit-testing { padding: 24px; max-width: 900px; }
.subtitle { color: #909399; margin: 0 0 20px; }
.search-bar { margin-bottom: 24px; }
.results { margin-top: 8px; }
.result-card {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 12px 16px;
  margin: 12px 0;
}
.result-header { display: flex; gap: 12px; align-items: center; margin-bottom: 8px; }
.score { color: #409eff; font-weight: 500; font-size: 13px; }
.doc-title { color: #909399; font-size: 13px; }
.heading { color: #e6a23c; font-size: 13px; }
.qa-question { margin: 4px 0; font-size: 14px; }
.qa-answer { color: #606266; font-size: 14px; margin-top: 4px; }
.chunk-content { white-space: pre-wrap; font-size: 14px; line-height: 1.7; }
.qa-card { border-left: 3px solid #67c23a; }
</style>
