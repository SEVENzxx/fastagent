<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Plus } from '@element-plus/icons-vue'
import * as marketingApi from '@/api/marketing'
import type { MarketingDocResponse, MarketingDocCreate, MarketingDocUpdate } from '@/api/marketing'

const docs = ref<MarketingDocResponse[]>([])
const loading = ref(true)
const total = ref(0)
const page = ref(1)
const pageSize = ref(12)

// -- dialog state
const dialogVisible = ref(false)
const editingDoc = ref<MarketingDocResponse | null>(null)
const form = ref({ title: '', fileType: 'link', questionAssociations: '' })

async function loadData() {
  loading.value = true
  try {
    const skip = (page.value - 1) * pageSize.value
    const result = await marketingApi.listMarketingDocs(skip, pageSize.value)
    docs.value = result.items
    total.value = result.total
  } catch {
    docs.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingDoc.value = null
  form.value = { title: '', fileType: 'link', questionAssociations: '' }
  dialogVisible.value = true
}

function openEdit(doc: MarketingDocResponse) {
  editingDoc.value = doc
  form.value = {
    title: doc.title,
    fileType: doc.fileType,
    questionAssociations: (doc.questionAssociations || []).join(', '),
  }
  dialogVisible.value = true
}

async function handleSave() {
  const qa = form.value.questionAssociations
    .split(/[,;，；]/)
    .map(s => s.trim())
    .filter(Boolean)

  if (editingDoc.value) {
    const data: MarketingDocUpdate = {
      title: form.value.title,
      fileType: form.value.fileType,
      questionAssociations: qa.length > 0 ? qa : undefined,
    }
    await marketingApi.updateMarketingDoc(editingDoc.value.id, data)
    ElMessage.success('已更新')
  } else {
    const data: MarketingDocCreate = {
      title: form.value.title,
      fileType: form.value.fileType,
    }
    await marketingApi.createMarketingDoc(data)
    ElMessage.success('已创建')
  }
  dialogVisible.value = false
  await loadData()
}

async function handleDelete(doc: MarketingDocResponse) {
  await ElMessageBox.confirm(`确定删除「${doc.title}」吗？`, '删除确认', { type: 'warning' })
  await marketingApi.deleteMarketingDoc(doc.id)
  ElMessage.success('已删除')
  await loadData()
}

onMounted(loadData)
</script>

<template>
  <div class="marketing-doc-list">
    <div class="page-header">
      <h2>营销资料</h2>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建资料</el-button>
    </div>

    <el-table :data="docs" v-loading="loading" stripe>
      <el-table-column prop="title" label="名称" min-width="200" />
      <el-table-column prop="fileType" label="类型" width="80" />
      <el-table-column label="关联场景" min-width="200">
        <template #default="{ row }">
          <template v-if="row.questionAssociations?.length">
            <el-tag v-for="q in row.questionAssociations" :key="q" size="small" style="margin: 2px">
              {{ q }}
            </el-tag>
          </template>
          <span v-else style="color: #c0c4cc">-</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.isActive ? 'success' : 'info'" size="small">
            {{ row.isActive ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button text type="primary" size="small" :icon="Plus" @click="openEdit(row)" />
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

    <el-dialog
      v-model="dialogVisible"
      :title="editingDoc ? '编辑资料' : '新建资料'"
      width="480px"
      @closed="form = { title: '', fileType: 'link', questionAssociations: '' }"
    >
      <el-form label-position="top">
        <el-form-item label="名称">
          <el-input v-model="form.title" placeholder="资料名称" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.fileType">
            <el-option label="链接" value="link" />
            <el-option label="PDF" value="pdf" />
            <el-option label="Word" value="docx" />
            <el-option label="图片" value="image" />
          </el-select>
        </el-form-item>
        <el-form-item label="关联场景（逗号分隔）">
          <el-input v-model="form.questionAssociations" placeholder="例如：茶叶介绍, 价格咨询" />
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
.marketing-doc-list { padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h2 { margin: 0; }
.pagination-wrap { display: flex; justify-content: center; margin-top: 16px; }
</style>
