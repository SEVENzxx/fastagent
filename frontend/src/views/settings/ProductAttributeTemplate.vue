<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, RefreshRight, Delete, Edit, InfoFilled } from '@element-plus/icons-vue'
import * as tenantApi from '@/api/tenant'
import * as categoriesApi from '@/api/categories'
import type { AttributeDef, CategoryAttrOption } from '@/api/tenant'

const loading = ref(false)
const saving = ref(false)
const attributes = ref<AttributeDef[]>([])
const savedJson = ref('')
const showEditor = ref(false)
const editingIndex = ref(-1)
const editMode = ref<'form' | 'json'>('form')
const jsonInput = ref('')

// ── 分类选择 ──
const categories = ref<CategoryAttrOption[]>([])
const selectedCategoryId = ref('')
const selectedCategoryName = ref('全部分类')

const attrTypes = [
  { label: '布尔值', value: 'boolean' },
  { label: '数值', value: 'number' },
  { label: '枚举', value: 'enum' },
  { label: '文本', value: 'text' },
] as const

const queryStrategies = [
  { label: '布尔匹配 (jsonb_bool)', value: 'jsonb_bool' },
  { label: '数值匹配 (jsonb_number)', value: 'jsonb_number' },
  { label: '模糊文本 (jsonb_text)', value: 'jsonb_text' },
  { label: '精确匹配 (jsonb_equals)', value: 'jsonb_equals' },
  { label: '数组包含 (jsonb_contains)', value: 'jsonb_contains' },
]

const defaultAttr = (): AttributeDef => ({
  key: '',
  label: '',
  type: 'boolean',
  aliases: [],
  description: '',
  queryPath: ['attr', ''],
  queryStrategy: 'jsonb_bool',
  unit: null,
  allowedValues: [],
})

const form = reactive<AttributeDef>(defaultAttr())
const aliasInput = ref('')
const allowedValueInput = ref('')

const hasChanges = computed(() => JSON.stringify(attributes.value) !== savedJson.value)
const jsonPreview = computed(() =>
  JSON.stringify({ attributes: attributes.value }, null, 2)
)

function switchToJsonMode() {
  jsonInput.value = JSON.stringify(attributes.value, null, 2)
  editMode.value = 'json'
}

function applyJson() {
  let parsed: any
  try {
    parsed = JSON.parse(jsonInput.value)
  } catch (e: any) {
    ElMessage.error(`JSON 格式错误: ${e.message}`)
    return
  }
  if (!Array.isArray(parsed)) {
    ElMessage.error('JSON 必须是属性定义的数组')
    return
  }
  for (let i = 0; i < parsed.length; i++) {
    const item = parsed[i]
    if (!item.key || !item.label) {
      ElMessage.error(`第 ${i + 1} 项缺少 key 或 label`)
      return
    }
    const values = item.allowed_values || item.allowedValues
    if (item.type === 'enum' && (!values || values.length === 0)) {
      ElMessage.error(`属性 "${item.key}" 是 enum 类型但未配置 allowed_values`)
      return
    }
  }
  attributes.value = parsed
  ElMessage.success(`已导入 ${parsed.length} 个属性`)
  editMode.value = 'form'
}

// ── 加载分类列表（仅叶子节点分类）──
async function loadCategories() {
  try {
    const cats = await categoriesApi.getCategories()
    const parentIds = new Set(cats.map((c) => c.parentId).filter(Boolean))
    const leafCats = cats.filter((c) => !parentIds.has(c.id))
    const configured = await tenantApi.getTemplateCategories().catch(() => [])
    const countMap: Record<string, number> = {}
    for (const c of configured) {
      countMap[c.categoryId] = c.attrCount
    }
    categories.value = leafCats.map((c) => ({
      categoryId: c.id,
      categoryName: c.name,
      attrCount: countMap[c.id] || 0,
    }))
    categories.value.unshift({ categoryId: '', categoryName: '全部分类', attrCount: 0 })
  } catch {
    categories.value = [{ categoryId: '', categoryName: '全部分类', attrCount: 0 }]
  }
}

// ── 切换分类：从 template 的 @change 显式触发，避免 watch 异步竞态 ──
async function handleCategoryChange(categoryId: string) {
  selectedCategoryId.value = categoryId
  const cat = categories.value.find((c) => c.categoryId === categoryId)
  selectedCategoryName.value = cat?.categoryName || '全部分类'
  editMode.value = 'form'
  await loadTemplate()
}

function openEditor(index: number = -1) {
  editingIndex.value = index
  if (index >= 0) {
    Object.assign(form, JSON.parse(JSON.stringify(attributes.value[index])))
  } else {
    Object.assign(form, defaultAttr())
  }
  aliasInput.value = ''
  allowedValueInput.value = ''
  showEditor.value = true
}

function closeEditor() {
  showEditor.value = false
  editingIndex.value = -1
}

function saveEditor() {
  if (!form.key.trim()) {
    ElMessage.warning('属性 key 不能为空')
    return
  }
  if (!form.label.trim()) {
    ElMessage.warning('属性 label 不能为空')
    return
  }
  if (form.type === 'enum' && !form.allowedValues?.length) {
    ElMessage.warning('enum 类型必须配置至少一个可选值')
    return
  }

  form.queryPath = ['attr', form.key]

  if (!form.queryStrategy) {
    const strategyMap: Record<string, AttributeDef['queryStrategy']> = {
      boolean: 'jsonb_bool',
      number: 'jsonb_number',
      enum: 'jsonb_equals',
      text: 'jsonb_text',
    }
    form.queryStrategy = strategyMap[form.type] || 'jsonb_text'
  }

  const existing = editingIndex.value >= 0 ? editingIndex.value : -1
  const dupKey = attributes.value.findIndex((a, i) => a.key === form.key && i !== existing)
  if (dupKey >= 0) {
    ElMessage.warning(`属性 key "${form.key}" 已存在`)
    return
  }

  const saved = JSON.parse(JSON.stringify(form))
  if (editingIndex.value >= 0) {
    attributes.value[editingIndex.value] = saved
  } else {
    attributes.value.push(saved)
  }
  closeEditor()
}

function addAlias() {
  const v = aliasInput.value.trim()
  if (!v) return
  if (form.aliases.includes(v)) {
    ElMessage.warning('别名已存在')
    return
  }
  form.aliases.push(v)
  aliasInput.value = ''
}

function removeAlias(index: number) {
  form.aliases.splice(index, 1)
}

function addAllowedValue() {
  const v = allowedValueInput.value.trim()
  if (!v) return
  if (!form.allowedValues) form.allowedValues = []
  if (form.allowedValues.includes(v)) {
    ElMessage.warning('可选值已存在')
    return
  }
  form.allowedValues.push(v)
  allowedValueInput.value = ''
}

function removeAllowedValue(index: number) {
  form.allowedValues?.splice(index, 1)
}

function removeAttribute(index: number) {
  attributes.value.splice(index, 1)
}

async function loadTemplate() {
  loading.value = true
  try {
    const result = await tenantApi.getTenantTemplate(
      selectedCategoryId.value || undefined
    )
    attributes.value = result.attributes || []
    savedJson.value = JSON.stringify(attributes.value)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '加载属性配置失败')
  } finally {
    loading.value = false
  }
}

async function saveTemplate() {
  if (!selectedCategoryId.value) {
    ElMessage.warning('请先选择一个分类')
    return
  }
  saving.value = true
  try {
    const result = await tenantApi.updateTenantTemplate({
      categoryId: selectedCategoryId.value,
      attributes: attributes.value,
    })
    attributes.value = result.attributes || []
    savedJson.value = JSON.stringify(attributes.value)
    const idx = categories.value.findIndex((c) => c.categoryId === selectedCategoryId.value)
    if (idx >= 0) {
      categories.value[idx] = {
        ...categories.value[idx],
        attrCount: attributes.value.length,
      }
    }
    ElMessage.success(`「${selectedCategoryName.value}」属性配置已保存`)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '保存属性配置失败')
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
  attributes.value = JSON.parse(savedJson.value || '[]')
}

onMounted(async () => {
  await loadCategories()
  const configured = categories.value.find((c) => c.attrCount > 0)
  if (configured && configured.categoryId) {
    selectedCategoryId.value = configured.categoryId
    const cat = categories.value.find((c) => c.categoryId === configured.categoryId)
    selectedCategoryName.value = cat?.categoryName || '全部分类'
  }
  await loadTemplate()
})
</script>

<template>
  <section class="template-page" v-loading="loading">
    <header class="page-header">
      <div>
        <p>商品配置</p>
        <h2>商品属性 Schema</h2>
      </div>
      <el-tag type="info" effect="light">{{ attributes.length }} 个属性</el-tag>
    </header>

    <!-- 分类选择器 -->
    <section class="category-bar">
      <span class="category-label">配置分类：</span>
      <el-select
        v-model="selectedCategoryId"
        placeholder="请选择分类"
        filterable
        style="width: 300px"
        @change="handleCategoryChange"
      >
        <el-option
          v-for="cat in categories"
          :key="cat.categoryId"
          :label="`${cat.categoryName}${cat.attrCount > 0 ? `（${cat.attrCount} 个属性）` : '（未配置）'}`"
          :value="cat.categoryId"
        />
      </el-select>
      <span v-if="selectedCategoryId" class="category-hint">
        当前配置：<strong>{{ selectedCategoryName }}</strong>
      </span>
      <span v-else class="category-hint-warning">
        请先选择分类后再配置属性
      </span>
    </section>

    <section class="template-grid">
      <!-- 左侧：属性列表 + 操作 -->
      <div class="editor-panel">
        <div class="panel-heading">
          <h3>属性列表</h3>
          <div style="display: flex; gap: 8px">
            <el-button
              v-if="editMode === 'form'"
              :icon="RefreshRight"
              :disabled="!hasChanges || saving"
              plain
              @click="resetChanges"
            >
              重置
            </el-button>
            <el-button
              v-if="editMode === 'form'"
              type="primary"
              :icon="Plus"
              :disabled="!selectedCategoryId"
              @click="openEditor(-1)"
            >
              新增属性
            </el-button>
            <el-button
              v-if="editMode === 'form'"
              @click="switchToJsonMode"
              :disabled="!selectedCategoryId"
            >
              JSON 模式
            </el-button>
            <el-button
              v-if="editMode === 'json'"
              type="primary"
              @click="applyJson"
            >
              应用 JSON
            </el-button>
            <el-button
              v-if="editMode === 'json'"
              @click="editMode = 'form'"
            >
              取消
            </el-button>
          </div>
        </div>

        <!-- JSON 编辑模式 -->
        <div v-if="editMode === 'json'" style="margin-bottom: 16px;">
          <p style="margin: 0 0 8px; font-size: 13px; color: #909399;">
            直接粘贴属性定义的 JSON 数组，点击「应用 JSON」导入
          </p>
          <el-input
            v-model="jsonInput"
            type="textarea"
            :rows="22"
            placeholder='[{ "key": "brand", "label": "品牌", "type": "enum", "allowed_values": ["苹果", "华为", ...] }, ...]'
            style="font-family: monospace; font-size: 13px;"
          />
        </div>

        <!-- 表单模式 -->
        <template v-if="editMode === 'form'">
          <div class="attr-table" v-if="attributes.length">
            <div class="attr-table-header">
              <span class="col-key">Key</span>
              <span class="col-label">名称</span>
              <span class="col-type">类型</span>
              <span class="col-strategy">查询</span>
              <span class="col-actions">操作</span>
            </div>
            <div class="attr-row" v-for="(attr, index) in attributes" :key="attr.key">
              <span class="col-key"><code>{{ attr.key }}</code></span>
              <span class="col-label">{{ attr.label }}</span>
              <span class="col-type">
                <el-tag size="small" :type="attr.type === 'boolean' ? 'success' : attr.type === 'number' ? 'warning' : attr.type === 'enum' ? 'danger' : ''">
                  {{ attr.type }}
                </el-tag>
              </span>
              <span class="col-strategy" :title="attr.queryStrategy">{{ attr.queryStrategy?.replace('jsonb_', '') }}</span>
              <span class="col-actions">
                <el-button text :icon="Edit" size="small" @click="openEditor(index)">编辑</el-button>
                <el-button text :icon="Delete" type="danger" size="small" @click="removeAttribute(index)">删除</el-button>
              </span>
            </div>
          </div>
          <el-empty v-else description="暂无属性配置" :image-size="88" />
        </template>

        <div class="actions" v-if="attributes.length">
          <el-button
            type="primary"
            :loading="saving"
            :disabled="!hasChanges || !selectedCategoryId"
            @click="saveTemplate"
            size="large"
          >
            保存配置
          </el-button>
        </div>
      </div>

      <!-- 右侧：JSON 预览 -->
      <div class="preview-panel">
        <div class="panel-heading">
          <h3>JSON 预览</h3>
        </div>
        <pre>{{ jsonPreview }}</pre>
      </div>
    </section>

    <!-- 属性编辑弹窗 -->
    <el-dialog
      v-model="showEditor"
      :title="editingIndex >= 0 ? '编辑属性' : '新增属性'"
      width="640px"
      destroy-on-close
    >
      <el-form label-position="top" class="attr-form">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="属性 Key" required>
              <el-input v-model="form.key" placeholder="如 is_waterproof" maxlength="64" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="显示名称" required>
              <el-input v-model="form.label" placeholder="如 防水" maxlength="32" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="值类型" required>
              <el-select v-model="form.type" style="width: 100%">
                <el-option
                  v-for="t in attrTypes"
                  :key="t.value"
                  :label="t.label"
                  :value="t.value"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="SQL 查询策略">
              <el-select v-model="form.queryStrategy" style="width: 100%">
                <el-option
                  v-for="s in queryStrategies"
                  :key="s.value"
                  :label="s.label"
                  :value="s.value"
                />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="属性说明">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="2"
            placeholder="LLM 抽取时的判断依据，如『商品是否具备防水、防泼水能力』"
          />
        </el-form-item>

        <el-form-item v-if="form.type === 'number'" label="数值单位">
          <el-input v-model="form.unit" placeholder="如 天 / 小时 / mm" maxlength="10" />
        </el-form-item>

        <el-form-item label="同义别名（帮助 LLM 匹配）">
          <div class="tag-input">
            <el-input
              v-model="aliasInput"
              placeholder="输入别名后按回车添加"
              maxlength="20"
              @keyup.enter="addAlias"
            />
            <el-button :icon="Plus" @click="addAlias" :disabled="!aliasInput.trim()">添加</el-button>
          </div>
          <div class="tag-list" v-if="form.aliases.length">
            <el-tag
              v-for="(a, i) in form.aliases"
              :key="a"
              closable
              @close="removeAlias(i)"
            >
              {{ a }}
            </el-tag>
          </div>
        </el-form-item>

        <el-form-item v-if="form.type === 'enum'" label="可选值列表" required>
          <div class="tag-input">
            <el-input
              v-model="allowedValueInput"
              placeholder="输入可选值后按回车添加"
              maxlength="20"
              @keyup.enter="addAllowedValue"
            />
            <el-button :icon="Plus" @click="addAllowedValue" :disabled="!allowedValueInput.trim()">添加</el-button>
          </div>
          <div class="tag-list" v-if="form.allowedValues?.length">
            <el-tag
              v-for="(v, i) in form.allowedValues"
              :key="v"
              closable
              @close="removeAllowedValue(i)"
            >
              {{ v }}
            </el-tag>
          </div>
        </el-form-item>

        <el-alert
          v-if="form.key"
          :title="`SQL 查询路径：attrs_json -> 'attr' -> '${form.key}'`"
          type="info"
          :closable="false"
          show-icon
          :icon="InfoFilled"
          style="margin-top: 8px"
        />
      </el-form>

      <template #footer>
        <el-button @click="closeEditor">取消</el-button>
        <el-button type="primary" @click="saveEditor">确定</el-button>
      </template>
    </el-dialog>
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

.category-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 20px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
}

.category-label {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-strong);
  white-space: nowrap;
}

.category-hint {
  font-size: 13px;
  color: var(--color-primary);
}

.category-hint-warning {
  font-size: 13px;
  color: var(--color-warning);
}

.template-grid {
  display: grid;
  grid-template-columns: minmax(480px, 1.2fr) minmax(360px, 0.8fr);
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

.panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.attr-table {
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}

.attr-table-header,
.attr-row {
  display: grid;
  grid-template-columns: 140px 100px 70px 90px 1fr;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
}

.attr-table-header {
  background: var(--surface-soft);
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 600;
  border-bottom: 1px solid var(--border);
}

.attr-row {
  border-bottom: 1px solid var(--border-subtle);
  font-size: 13px;
}

.attr-row:last-child {
  border-bottom: none;
}

.attr-row:hover {
  background: var(--surface-soft);
}

.col-key code {
  font-size: 12px;
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--surface-soft);
  color: var(--color-primary);
}

.col-actions {
  text-align: right;
}

.tag-input {
  display: flex;
  gap: 8px;
  width: 100%;
}

.tag-input .el-input {
  flex: 1;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.attr-form .el-form-item {
  margin-bottom: 16px;
}

.actions {
  display: flex;
  justify-content: flex-end;
}

.preview-panel pre {
  min-height: 300px;
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

@media (max-width: 1024px) {
  .template-grid {
    grid-template-columns: 1fr;
  }
}
</style>
