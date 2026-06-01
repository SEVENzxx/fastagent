<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Edit, Plus } from '@element-plus/icons-vue'
import * as knowledgeApi from '@/api/knowledge'
import type { QAPairResponse, QAPairCreate, QAPairUpdate } from '@/api/knowledge'

const pairs = ref<QAPairResponse[]>([])
const loading = ref(true)
const total = ref(0)
const page = ref(1)
const pageSize = ref(12)

// -- dialog state
const dialogVisible = ref(false)
const editingPair = ref<QAPairResponse | null>(null)
const form = ref({ question: '', answer: '', keywords: '' })

async function loadData() {
  loading.value = true
  try {
    const skip = (page.value - 1) * pageSize.value
    const result = await knowledgeApi.listQAPairs(skip, pageSize.value)
    pairs.value = result.items
    total.value = result.total
  } catch {
    pairs.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingPair.value = null
  form.value = { question: '', answer: '', keywords: '' }
  dialogVisible.value = true
}

function openEdit(pair: QAPairResponse) {
  editingPair.value = pair
  form.value = {
    question: pair.question,
    answer: pair.answer,
    keywords: (pair.keywords || []).join(', '),
  }
  dialogVisible.value = true
}

async function handleSave() {
  const keywords = form.value.keywords
    .split(/[,;，；]/)
    .map(k => k.trim())
    .filter(Boolean)

  if (editingPair.value) {
    const data: QAPairUpdate = {
      question: form.value.question,
      answer: form.value.answer,
      keywords: keywords.length > 0 ? keywords : undefined,
    }
    await knowledgeApi.updateQAPair(editingPair.value.id, data)
    ElMessage.success('已更新')
  } else {
    const data: QAPairCreate = {
      question: form.value.question,
      answer: form.value.answer,
      keywords: keywords.length > 0 ? keywords : undefined,
    }
    await knowledgeApi.createQAPair(data)
    ElMessage.success('已创建')
  }
  dialogVisible.value = false
  await loadData()
}

async function handleDelete(pair: QAPairResponse) {
  await ElMessageBox.confirm(`确定删除该问答对吗？`, '删除确认', { type: 'warning' })
  await knowledgeApi.deleteQAPair(pair.id)
  ElMessage.success('已删除')
  await loadData()
}

async function toggleActive(pair: QAPairResponse) {
  await knowledgeApi.updateQAPair(pair.id, { isActive: !pair.isActive })
  ElMessage.success(pair.isActive ? '已停用' : '已启用')
  await loadData()
}

onMounted(loadData)
</script>

<template>
  <div class="qa-pair-list">
    <div class="page-header">
      <h2>问答对</h2>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建问答对</el-button>
    </div>

    <el-table :data="pairs" v-loading="loading" stripe>
      <el-table-column prop="question" label="问题" min-width="200" show-overflow-tooltip />
      <el-table-column prop="answer" label="答案" min-width="250" show-overflow-tooltip />
      <el-table-column prop="keywords" label="关键词" width="150">
        <template #default="{ row }">
          <template v-if="row.keywords?.length">
            <el-tag v-for="kw in row.keywords" :key="kw" size="small" style="margin: 2px">
              {{ kw }}
            </el-tag>
          </template>
          <span v-else style="color: #c0c4cc">-</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-switch :model-value="row.isActive" size="small" @change="toggleActive(row)" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
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

    <!-- create/edit dialog -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingPair ? '编辑问答对' : '新建问答对'"
      width="560px"
      @closed="form = { question: '', answer: '', keywords: '' }"
    >
      <el-form label-position="top">
        <el-form-item label="问题">
          <el-input v-model="form.question" placeholder="输入标准问题" />
        </el-form-item>
        <el-form-item label="答案">
          <el-input v-model="form.answer" type="textarea" :rows="4" placeholder="输入标准答案" />
        </el-form-item>
        <el-form-item label="关键词（逗号分隔）">
          <el-input v-model="form.keywords" placeholder="例如：茶叶, 龙井, 价格" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.qa-pair-list { padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h2 { margin: 0; }
.pagination-wrap { display: flex; justify-content: center; margin-top: 16px; }
</style>
