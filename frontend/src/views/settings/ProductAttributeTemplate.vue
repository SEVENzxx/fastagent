<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, RefreshRight } from '@element-plus/icons-vue'
import * as tenantApi from '@/api/tenant'

const loading = ref(false)
const saving = ref(false)
const fields = ref<string[]>([])
const savedFields = ref<string[]>([])
const newField = ref('')

const jsonPreview = computed(() => JSON.stringify(fields.value, null, 2))
const hasChanges = computed(() => JSON.stringify(fields.value) !== JSON.stringify(savedFields.value))

function normalizeField(value: string) {
  return value.trim()
}

function addField() {
  const field = normalizeField(newField.value)
  if (!field) {
    ElMessage.warning('字段名不能为空')
    return
  }
  if (fields.value.includes(field)) {
    ElMessage.warning('字段已存在')
    return
  }
  fields.value.push(field)
  newField.value = ''
}

function removeField(index: number) {
  fields.value.splice(index, 1)
}

async function loadTemplate() {
  loading.value = true
  try {
    const result = await tenantApi.getTenantTemplate()
    fields.value = [...result.templateJson]
    savedFields.value = [...result.templateJson]
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '加载属性模板失败')
  } finally {
    loading.value = false
  }
}

async function saveTemplate() {
  saving.value = true
  try {
    const result = await tenantApi.updateTenantTemplate(fields.value)
    fields.value = [...result.templateJson]
    savedFields.value = [...result.templateJson]
    ElMessage.success('属性模板已保存')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '保存属性模板失败')
  } finally {
    saving.value = false
  }
}

async function resetChanges() {
  if (!hasChanges.value) return
  await ElMessageBox.confirm('放弃当前未保存的修改？', '确认重置', {
    type: 'warning',
    confirmButtonText: '重置',
    cancelButtonText: '取消',
  })
  fields.value = [...savedFields.value]
  newField.value = ''
}

onMounted(loadTemplate)
</script>

<template>
  <section class="template-page" v-loading="loading">
    <header class="page-header">
      <div>
        <p>商品配置</p>
        <h2>自定义属性模板</h2>
      </div>
      <el-tag type="info" effect="light">{{ fields.length }} 个字段</el-tag>
    </header>

    <section class="template-grid">
      <div class="editor-panel">
        <div class="panel-heading">
          <h3>字段列表</h3>
          <el-button :icon="RefreshRight" :disabled="!hasChanges || saving" plain @click="resetChanges">
            重置
          </el-button>
        </div>

        <div class="field-input">
          <el-input
            v-model="newField"
            placeholder="输入字段名"
            maxlength="50"
            show-word-limit
            @keyup.enter="addField"
          />
          <el-button type="primary" :icon="Plus" @click="addField">添加</el-button>
        </div>

        <div class="field-list">
          <el-empty v-if="!fields.length" description="暂无字段" :image-size="88" />
          <el-tag
            v-for="(field, index) in fields"
            v-else
            :key="field"
            closable
            effect="plain"
            @close="removeField(index)"
          >
            {{ field }}
          </el-tag>
        </div>

        <div class="actions">
          <el-button type="primary" :loading="saving" :disabled="!hasChanges" @click="saveTemplate">
            保存模板
          </el-button>
        </div>
      </div>

      <div class="preview-panel">
        <div class="panel-heading">
          <h3>JSON</h3>
        </div>
        <pre>{{ jsonPreview }}</pre>
      </div>
    </section>
  </section>
</template>

<style scoped>
.template-page {
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
.panel-heading h3 {
  margin: 0;
  color: var(--text-strong);
}

.template-grid {
  display: grid;
  grid-template-columns: minmax(360px, 1fr) minmax(320px, 0.8fr);
  gap: 18px;
}

.editor-panel,
.preview-panel {
  display: grid;
  align-content: start;
  gap: 16px;
  padding: 20px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
}

.panel-heading,
.field-input,
.actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.field-input .el-input {
  flex: 1;
}

.field-list {
  min-height: 180px;
  display: flex;
  align-content: flex-start;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-soft);
}

.preview-panel pre {
  min-height: 220px;
  margin: 0;
  padding: 14px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #0f172a;
  color: #e2e8f0;
  font-size: 13px;
  line-height: 1.6;
}

@media (max-width: 980px) {
  .template-grid {
    grid-template-columns: 1fr;
  }

  .field-input,
  .actions {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
