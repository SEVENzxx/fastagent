<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Edit, Plus, Search, Upload } from '@element-plus/icons-vue'
import { isAxiosError } from 'axios'
import * as api from '@/api/intentSamples'
import type {
  IntentSampleResponse,
  IntentSampleCreate,
  IntentSampleUpdate,
  IntentSampleTestHit,
} from '@/api/intentSamples'

// ── Data ──
const items = ref<IntentSampleResponse[]>([])
const loading = ref(true)
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

// ── Filters ──
const filterScenarioId = ref('')
const filterEnabled = ref<boolean | ''>('')

// ── Create/Edit Dialog ──
const dialogVisible = ref(false)
const editingItem = ref<IntentSampleResponse | null>(null)
const saving = ref(false)
const form = ref<IntentSampleCreate>({
  scenarioId: '',
  label: '',
  exampleText: '',
  enabled: true,
})

// ── Batch Create Dialog ──
const batchDialogVisible = ref(false)
const batchSaving = ref(false)
const batchForm = ref({
  scenarioId: '',
  label: '',
  examples: '',
  enabled: true,
})

// ── Test Search ──
const searchQuery = ref('')
const searchLoading = ref(false)
const searchResults = ref<IntentSampleTestHit[]>([])

// ── Load Data ──
async function loadData() {
  loading.value = true
  try {
    const skip = (page.value - 1) * pageSize.value
    const params: Record<string, any> = { skip, limit: pageSize.value }
    if (filterScenarioId.value) params.scenario_id = filterScenarioId.value
    if (filterEnabled.value !== '') params.enabled = filterEnabled.value
    const result = await api.listIntentSamples(params)
    items.value = result.items
    total.value = result.total
  } catch {
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

// ── Create / Edit ──
function openCreate() {
  editingItem.value = null
  form.value = { scenarioId: '', label: '', exampleText: '', enabled: true }
  dialogVisible.value = true
}

function openEdit(item: IntentSampleResponse) {
  editingItem.value = item
  form.value = {
    scenarioId: item.scenarioId,
    label: item.label,
    exampleText: item.exampleText,
    enabled: item.enabled,
  }
  dialogVisible.value = true
}

async function handleSave() {
  if (!form.value.scenarioId || !form.value.label || !form.value.exampleText) {
    ElMessage.warning('请填写完整信息')
    return
  }
  if (!form.value.scenarioId.includes('.')) {
    ElMessage.warning('场景标识必须包含点号，如 product.catalog')
    return
  }
  saving.value = true
  try {
    if (editingItem.value) {
      const data: IntentSampleUpdate = { ...form.value }
      await api.updateIntentSample(editingItem.value.id, data)
      ElMessage.success('已更新')
    } else {
      await api.createIntentSample(form.value)
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    await loadData()
  } catch (error) {
    const msg = isAxiosError(error) ? error.response?.data?.detail : null
    ElMessage.error(msg || '保存失败')
  } finally {
    saving.value = false
  }
}

// ── Batch Create ──
function openBatchCreate() {
  batchForm.value = { scenarioId: '', label: '', examples: '', enabled: true }
  batchDialogVisible.value = true
}

async function handleBatchSave() {
  if (!batchForm.value.scenarioId || !batchForm.value.label || !batchForm.value.examples.trim()) {
    ElMessage.warning('请填写完整信息')
    return
  }
  if (!batchForm.value.scenarioId.includes('.')) {
    ElMessage.warning('场景标识必须包含点号，如 product.catalog')
    return
  }
  const examples = batchForm.value.examples.split('\n').map((s) => s.trim()).filter(Boolean)
  if (examples.length === 0) {
    ElMessage.warning('请至少输入一条样本文本')
    return
  }
  batchSaving.value = true
  try {
    await api.batchCreateIntentSamples({
      scenarioId: batchForm.value.scenarioId,
      label: batchForm.value.label,
      examples,
      enabled: batchForm.value.enabled,
    })
    ElMessage.success(`已创建 ${examples.length} 条样本`)
    batchDialogVisible.value = false
    await loadData()
  } catch (error) {
    const msg = isAxiosError(error) ? error.response?.data?.detail : null
    ElMessage.error(msg || '批量创建失败')
  } finally {
    batchSaving.value = false
  }
}

// ── Toggle / Delete ──
async function handleToggle(item: IntentSampleResponse) {
  try {
    await api.toggleIntentSampleEnabled(item.id, !item.enabled)
    ElMessage.success(item.enabled ? '已停用' : '已启用')
    await loadData()
  } catch (error) {
    const msg = isAxiosError(error) ? error.response?.data?.detail : null
    ElMessage.error(msg || '操作失败')
  }
}

async function handleDelete(item: IntentSampleResponse) {
  await ElMessageBox.confirm(`确定删除这条「${item.label}」样本吗？`, '删除确认', { type: 'warning' })
  try {
    await api.deleteIntentSample(item.id)
    ElMessage.success('已删除')
    await loadData()
  } catch (error) {
    const msg = isAxiosError(error) ? error.response?.data?.detail : null
    ElMessage.error(msg || '删除失败')
  }
}

// ── Test Search ──
async function handleTestSearch() {
  if (!searchQuery.value.trim()) return
  searchLoading.value = true
  searchResults.value = []
  try {
    const result = await api.testSearchIntentSamples(searchQuery.value.trim())
    searchResults.value = result.results
    if (result.results.length === 0) {
      ElMessage.info('未找到匹配结果')
    }
  } catch (error) {
    const msg = isAxiosError(error) ? error.response?.data?.detail : null
    ElMessage.error(msg || '检索失败')
  } finally {
    searchLoading.value = false
  }
}

// ── Display helpers ──
const sourceLabelMap: Record<string, string> = {
  platform_default: '平台默认',
  tenant_custom: '自定义',
}

onMounted(() => {
  loadData()
})
</script>

<template>
  <div class="intent-sample-list">
    <div class="page-header">
      <h2>场景样本管理</h2>
      <div class="header-actions">
        <el-button :icon="Search" @click="$nextTick(() => document.getElementById('search-input')?.focus())">
          测试召回
        </el-button>
        <el-button :icon="Upload" @click="openBatchCreate">批量新增</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">新增样本</el-button>
      </div>
    </div>

    <!-- Filters -->
    <div class="filters">
      <el-input v-model="filterScenarioId" placeholder="搜索 scenario_id" clearable style="width: 200px" @clear="loadData" @keyup.enter="loadData" />
      <el-select v-model="filterEnabled" placeholder="状态" clearable style="width: 110px" @change="loadData">
        <el-option label="仅启用" :value="true" />
        <el-option label="仅停用" :value="false" />
      </el-select>
      <el-button @click="loadData">查询</el-button>
    </div>

    <!-- Table -->
    <el-table :data="items" v-loading="loading" stripe>
      <el-table-column prop="scenarioId" label="场景标识" width="170" />
      <el-table-column prop="label" label="场景名称" width="120" />
      <el-table-column prop="exampleText" label="样本文本" min-width="200" show-overflow-tooltip />
      <el-table-column prop="source" label="来源" width="80">
        <template #default="{ row }">
          {{ sourceLabelMap[row.source] || row.source }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="70">
        <template #default="{ row }">
          <el-switch :model-value="row.enabled" size="small" @click.prevent @change="handleToggle(row)" />
        </template>
      </el-table-column>
      <el-table-column prop="createdAt" label="创建时间" width="100">
        <template #default="{ row }">
          {{ row.createdAt?.slice(0, 10) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="130" fixed="right">
        <template #default="{ row }">
          <el-button text type="primary" size="small" :icon="Edit" @click="openEdit(row)" />
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

    <!-- ── Test Search Panel ── -->
    <el-divider />
    <div class="test-search">
      <h3>测试召回</h3>
      <p class="subtitle">输入一句用户消息，查看场景样本向量召回结果</p>
      <div class="search-bar">
        <el-input
          id="search-input"
          v-model="searchQuery"
          placeholder="输入测试问题，例如：你们有什么产品？"
          clearable
          @keyup.enter="handleTestSearch"
        >
          <template #append>
            <el-button type="primary" :icon="Search" :loading="searchLoading" @click="handleTestSearch">
              检索
            </el-button>
          </template>
        </el-input>
      </div>
      <div v-if="searchResults.length > 0" class="results">
        <div v-for="(hit, idx) in searchResults" :key="idx" class="result-card">
          <div class="result-header">
            <el-tag size="small" type="primary">score: {{ hit.score }}</el-tag>
            <span class="result-scenario">{{ hit.scenarioId }} ({{ hit.label }})</span>
            <el-tag v-if="hit.source === 'tenant_custom'" size="small" type="warning">租户样本</el-tag>
          </div>
          <div class="result-text">匹配: {{ hit.exampleText }}</div>
        </div>
      </div>
    </div>

    <!-- ── Create/Edit Dialog ── -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingItem ? '编辑场景样本' : '新增场景样本'"
      width="560px"
      @closed="form = { scenarioId: '', label: '', exampleText: '', enabled: true }"
    >
      <el-form label-position="top">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="场景标识 (scenarioId)">
              <el-input v-model="form.scenarioId" placeholder="例如：product.catalog" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="场景名称 (label)">
              <el-input v-model="form.label" placeholder="例如：商品搜索" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="样本文本">
          <el-input v-model="form.exampleText" type="textarea" :rows="3" placeholder="输入用户可能发送的问句" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>

    <!-- ── Batch Create Dialog ── -->
    <el-dialog
      v-model="batchDialogVisible"
      title="批量新增场景样本"
      width="560px"
    >
      <el-form label-position="top">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="场景标识 (scenarioId)">
              <el-input v-model="batchForm.scenarioId" placeholder="例如：product.catalog" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="场景名称 (label)">
              <el-input v-model="batchForm.label" placeholder="例如：商品搜索" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="样本文本（一行一条）">
          <el-input v-model="batchForm.examples" type="textarea" :rows="6" placeholder="例如：&#10;有没有耳机&#10;想看看蓝牙耳机&#10;有啥耳机推荐" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="batchSaving" @click="handleBatchSave">批量创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.intent-sample-list { padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h2 { margin: 0; }
.header-actions { display: flex; gap: 8px; }
.filters { display: flex; gap: 12px; margin-bottom: 16px; align-items: center; }
.pagination-wrap { display: flex; justify-content: center; margin-top: 16px; }
.test-search { margin-top: 8px; }
.subtitle { color: #909399; margin: 0 0 12px; font-size: 13px; }
.search-bar { margin-bottom: 16px; }
.result-card {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px 14px;
  margin: 8px 0;
}
.result-header { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.result-scenario { font-weight: 500; font-size: 13px; color: #303133; }
.result-text { color: #909399; font-size: 13px; margin-top: 4px; }
</style>
