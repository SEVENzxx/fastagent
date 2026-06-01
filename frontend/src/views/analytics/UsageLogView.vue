<script setup lang="ts">
/** 计费与用量分析页面
 *
 *  展示本租户的 LLM 调用明细，按来源（意图识别/通用回复/Agent 生成/向量化/重排）
 *  分类统计 tokens 消耗和成本。后续可接图表库展示趋势。
 */
import { computed, onMounted, ref } from 'vue'
import * as api from '@/api/usage'

const loading = ref(false)
const items = ref<api.UsageLog[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(30)
const sourceFilter = ref('')

// ── 按来源分类汇总 ──
const sourceSummary = computed(() => {
  const map: Record<string, { tokens: number; cost: number; count: number }> = {}
  for (const item of items.value) {
    const key = item.source || 'unknown'
    if (!map[key]) map[key] = { tokens: 0, cost: 0, count: 0 }
    map[key].tokens += item.totalTokens
    map[key].cost += item.cost
    map[key].count += 1
  }
  // 中文标签映射
  const labels: Record<string, string> = {
    intent: '意图识别',
    general_reply: '通用回复',
    agent_generate: 'Agent 生成',
    embedding: '向量化',
    rerank: '重排序',
    ai_pipeline: 'AI 管线',
  }
  return Object.entries(map).map(([key, val]) => ({
    source: key,
    label: labels[key] || key,
    ...val,
  }))
})

// ── 总计 ──
const totalTokens = computed(() => items.value.reduce((s, i) => s + i.totalTokens, 0))
const totalCost = computed(() => items.value.reduce((s, i) => s + i.cost, 0))

async function load() {
  loading.value = true
  try {
    const params: Record<string, any> = { page: page.value, pageSize: pageSize.value }
    if (sourceFilter.value) params.source = sourceFilter.value
    const res = await api.listUsage(params)
    items.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

function onPageChange(p: number) {
  page.value = p
  load()
}

onMounted(load)
</script>

<template>
  <section>
    <h2>计费与用量</h2>
    <p>模型调用按来源记录 tokens、成本和耗时，帮助评估各业务环节的 AI 开销。</p>

    <!-- ── 汇总卡片 ── -->
    <div class="summary-row">
      <article class="summary-card">
        <span>本次查询总 Tokens</span>
        <strong>{{ totalTokens.toLocaleString() }}</strong>
      </article>
      <article class="summary-card">
        <span>本次查询总成本</span>
        <strong>¥{{ totalCost.toFixed(6) }}</strong>
      </article>
    </div>

    <!-- ── 来源分类 ── -->
    <el-card class="section-card">
      <template #header>按来源分类汇总</template>
      <el-table :data="sourceSummary" size="small" stripe>
        <el-table-column prop="label" label="调用来源" min-width="140" />
        <el-table-column prop="count" label="调用次数" width="100" />
        <el-table-column prop="tokens" label="Tokens 小计" width="130">
          <template #default="{ row }">{{ row.tokens.toLocaleString() }}</template>
        </el-table-column>
        <el-table-column prop="cost" label="成本小计" width="130">
          <template #default="{ row }">¥{{ row.cost.toFixed(6) }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- ── 筛选条件 ── -->
    <div class="filter-bar">
      <el-select v-model="sourceFilter" placeholder="按来源筛选" clearable @change="load" style="width: 160px">
        <el-option label="意图识别" value="intent" />
        <el-option label="通用回复" value="general_reply" />
        <el-option label="Agent 生成" value="agent_generate" />
        <el-option label="向量化" value="embedding" />
        <el-option label="重排序" value="rerank" />
      </el-select>
    </div>

    <!-- ── 明细表格 ── -->
    <el-table v-loading="loading" :data="items" stripe>
      <el-table-column prop="source" label="来源" width="130" />
      <el-table-column prop="model" label="模型" min-width="160" />
      <el-table-column prop="promptTokens" label="输入 Tokens" width="110" />
      <el-table-column prop="completionTokens" label="输出 Tokens" width="110" />
      <el-table-column prop="totalTokens" label="总 Tokens" width="100" />
      <el-table-column prop="cost" label="成本" width="110">
        <template #default="{ row }">¥{{ row.cost.toFixed(6) }}</template>
      </el-table-column>
      <el-table-column prop="latencyMs" label="耗时(ms)" width="100" />
      <el-table-column label="结果" width="70">
        <template #default="{ row }">
          <el-tag :type="row.success ? 'success' : 'danger'" size="small">{{ row.success ? '成功' : '失败' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="createdAt" label="时间" width="180">
        <template #default="{ row }">{{ new Date(row.createdAt).toLocaleString() }}</template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-if="total > pageSize"
      class="pagination"
      :current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="prev, pager, next"
      @current-change="onPageChange" />
  </section>
</template>

<style scoped>
h2 { margin: 0; color: var(--text-strong); font-size: 22px; }
p { margin: 6px 0 18px; color: var(--text-muted); font-size: 13px; }
.summary-row { display: flex; gap: 14px; margin-bottom: 16px; }
.summary-card { flex: 1; min-width: 180px; display: grid; gap: 8px; padding: 16px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); }
.summary-card span { color: var(--text-muted); font-size: 13px; }
.summary-card strong { color: var(--text-strong); font-size: 26px; }
.section-card { margin-bottom: 16px; }
.filter-bar { margin-bottom: 12px; }
.pagination { margin-top: 16px; justify-content: flex-end; }
</style>
