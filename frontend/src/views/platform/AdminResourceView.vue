<!--
  平台资源管理页面（AdminResourceView）
  ======================================
  功能定位：超级管理员专用的资源管理页面，通过 props.resource 切换管理租户、套餐、LLM 模型配置三种资源。
  复用策略：单个页面组件通过 props 驱动切换，避免为三种资源各写一个页面。
  三种资源类型：
    - tenants: 租户 CRUD（名称、企业标识、绑定套餐和模型、AI 人设）
    - plans: 套餐 CRUD（名称、功能开关 JSON、额度限制 JSON、月/年费用）
    - llm: LLM 模型配置 CRUD（供应商、API 地址/密钥、模型名称、用途类型、定价 JSON）
  关键设计：
    - 编辑时套餐的 features/limits 和模型的 pricing 以 JSON 字符串形式在 textarea 中编辑
    - LLM 编辑时 API Key 置空（后端不回显密钥，留空表示不修改）
    - 新建/编辑共享同一个 el-dialog，通过 editingId 区分模式
-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import * as adminApi from '@/api/admin'

/** 父组件传入的资源类型，决定当前管理哪种资源 */
const props = defineProps<{ resource: 'tenants' | 'plans' | 'llm' }>()

/** 表格加载状态 */
const loading = ref(false)
/** 新建/编辑对话框的显示状态 */
const dialogVisible = ref(false)
/** 当前正在编辑的记录 ID，为 null 表示新建模式 */
const editingId = ref<string | null>(null)
/** 表格数据列表 */
const items = ref<Array<adminApi.Tenant | adminApi.Plan | adminApi.LLMConfig>>([])
/** 套餐列表（租户管理时需要下拉选择套餐） */
const plans = ref<adminApi.Plan[]>([])
/** LLM 模型配置列表（租户管理时需要下拉选择模型） */
const configs = ref<adminApi.LLMConfig[]>([])
/** 表单数据，使用 Record 类型支持三种资源的动态字段 */
const form = ref<Record<string, any>>({})

/** 根据 resource prop 动态计算页面标题 */
const title = computed(() => ({ tenants: '租户管理', plans: '套餐管理', llm: 'LLM 模型池' })[props.resource])

/**
 * 加载数据：并行获取套餐和模型配置（租户管理时需要作为下拉选项），
 * 再根据当前资源类型获取对应的列表数据
 */
async function loadData() {
  loading.value = true
  try {
    ;[plans.value, configs.value] = await Promise.all([adminApi.listPlans(), adminApi.listLLMConfigs()])
    items.value = props.resource === 'tenants' ? await adminApi.listTenants() : props.resource === 'plans' ? plans.value : configs.value
  } finally {
    loading.value = false
  }
}

/**
 * 获取新建表单的初始值
 * 根据资源类型返回不同字段组合的空表单
 */
function initialForm() {
  if (props.resource === 'tenants') return { name: '', slug: '', planId: null, selectedLlmConfigId: null, customPrompt: '', isActive: true, adminEmail: '', adminPassword: '', adminDisplayName: '' }
  if (props.resource === 'plans') return { name: '', description: '', featuresText: '{}', limitsText: '{}', priceMonthly: null, priceYearly: null, isActive: true }
  return { name: '', provider: 'http', apiBase: '', apiKey: '', model: '', purpose: 'chat', pricingText: '{}', isActive: true }
}

/** 打开新建对话框：重置 editingId 为 null，填充空白表单 */
function openCreate() {
  editingId.value = null
  form.value = initialForm()
  dialogVisible.value = true
}

/**
 * 打开编辑对话框：回填已有数据到表单
 * 套餐和模型配置中有 JSON 字段（features/limits/pricing），
 * 需要序列化为格式化的 JSON 字符串才能在 textarea 中展示
 * LLM 模型编辑时 API Key 不展示（安全考虑），置空表示不修改
 */
function openEdit(item: any) {
  editingId.value = item.id
  form.value = { ...item }
  if (props.resource === 'plans') {
    form.value.featuresText = JSON.stringify(item.features || {}, null, 2)
    form.value.limitsText = JSON.stringify(item.limits || {}, null, 2)
  }
  if (props.resource === 'llm') {
    form.value.pricingText = JSON.stringify(item.pricing || {}, null, 2)
    form.value.apiKey = ''
  }
  dialogVisible.value = true
}

/**
 * 构建提交载荷：将表单的 JSON 字符串字段解析为对象，并清理临时字段
 * - 套餐：featuresText → features, limitsText → limits
 * - 模型：pricingText → pricing, apiKey 为空时删除该字段（不修改密钥）
 */
function payload() {
  const data = { ...form.value }
  if (props.resource === 'plans') {
    data.features = JSON.parse(data.featuresText || '{}')
    data.limits = JSON.parse(data.limitsText || '{}')
    delete data.featuresText
    delete data.limitsText
  }
  if (props.resource === 'llm') {
    data.pricing = JSON.parse(data.pricingText || '{}')
    delete data.pricingText
    if (!data.apiKey) delete data.apiKey
  }
  return data
}

/**
 * 保存：根据 editingId 决定调用 create 还是 update API
 * 成功后关闭对话框、刷新列表
 */
async function save() {
  try {
    const data = payload()
    if (props.resource === 'tenants') {
      if (editingId.value) {
        await adminApi.updateTenant(editingId.value, data)
        ElMessage.success('租户已更新')
      } else {
        const result: any = await adminApi.createTenant(data)
        dialogVisible.value = false
        ElMessageBox.alert(
          `管理员邮箱：${result.adminEmail}\n管理员密码：${result.adminPassword}\n\n请将账号密码安全交付给租户管理员。密码仅在此时显示一次。`,
          '租户创建成功',
          { confirmButtonText: '已记录', type: 'success' },
        )
        await loadData()
        return
      }
    } else if (props.resource === 'plans') {
      editingId.value ? await adminApi.updatePlan(editingId.value, data) : await adminApi.createPlan(data)
      ElMessage.success('保存成功')
    } else {
      editingId.value ? await adminApi.updateLLMConfig(editingId.value, data) : await adminApi.createLLMConfig(data)
      ElMessage.success('保存成功')
    }
    dialogVisible.value = false
    await loadData()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '保存失败，请检查 JSON 格式')
  }
}

// 组件挂载时加载数据
onMounted(loadData)
// 父组件切换 resource 时重新加载对应数据
watch(() => props.resource, loadData)
</script>

<template>
  <!-- 页面根容器 -->
  <section>
    <!-- 页面标题区：左侧标题 + 描述，右侧新建按钮 -->
    <div class="page-header">
      <div><h2>{{ title }}</h2><p>平台超级管理员专用配置区</p></div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建</el-button>
    </div>

    <!--
      数据表格：根据 resource 类型切换不同的列配置
      三种类型的表格共享"状态"和"操作"列
    -->
    <el-table v-loading="loading" :data="items" stripe>
      <!-- 租户表格列：名称、企业标识、套餐、模型 -->
      <template v-if="resource === 'tenants'">
        <el-table-column prop="name" label="租户" min-width="160" />
        <el-table-column prop="slug" label="企业标识" min-width="140" />
        <el-table-column prop="planName" label="套餐" width="120" />
        <el-table-column prop="selectedLlmConfigName" label="模型" min-width="140" />
      </template>
      <!-- 套餐表格列：名称、说明、月费、年费（单位为分） -->
      <template v-else-if="resource === 'plans'">
        <el-table-column prop="name" label="套餐" min-width="150" />
        <el-table-column prop="description" label="说明" min-width="180" />
        <el-table-column prop="priceMonthly" label="月费（分）" width="110" />
        <el-table-column prop="priceYearly" label="年费（分）" width="110" />
      </template>
      <!-- LLM 模型配置表格列：名称、供应商、模型名、用途、密钥状态 -->
      <template v-else>
        <el-table-column prop="name" label="配置名称" min-width="150" />
        <el-table-column prop="provider" label="供应商" width="110" />
        <el-table-column prop="model" label="模型" min-width="160" />
        <el-table-column prop="purpose" label="用途" width="100" />
        <el-table-column label="密钥" width="90"><template #default="{ row }">{{ row.hasApiKey ? '已配置' : '未配置' }}</template></el-table-column>
      </template>
      <!-- 通用列：状态标签（启用=绿色，停用=灰色） -->
      <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="row.isActive ? 'success' : 'info'" size="small">{{ row.isActive ? '启用' : '停用' }}</el-tag></template></el-table-column>
      <!-- 通用列：编辑按钮 -->
      <el-table-column label="操作" width="90"><template #default="{ row }"><el-button text type="primary" @click="openEdit(row)">编辑</el-button></template></el-table-column>
    </el-table>

    <!--
      新建/编辑对话框：共用同一个 el-dialog
      editingId 为 null → 新建模式，否则为编辑模式
      表单内容根据 resource 类型动态切换
    -->
    <el-dialog v-model="dialogVisible" :title="editingId ? `编辑${title}` : `新建${title}`" width="620px">
      <el-form label-position="top">
        <!-- 租户表单：名称、企业标识（slug）、绑定套餐、授权模型、AI 人设提示词 -->
        <template v-if="resource === 'tenants'">
          <el-form-item label="租户名称"><el-input v-model="form.name" /></el-form-item>
          <el-form-item label="企业标识"><el-input v-model="form.slug" /></el-form-item>
          <el-form-item label="套餐"><el-select v-model="form.planId" clearable><el-option v-for="item in plans" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
          <el-form-item label="授权模型"><el-select v-model="form.selectedLlmConfigId" clearable><el-option v-for="item in configs" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
          <el-form-item label="AI 人设"><el-input v-model="form.customPrompt" type="textarea" :rows="4" placeholder="AI 客服人设提示词（可选）" /></el-form-item>
          <!-- 管理员账号：仅在新建时显示，编辑时不显示 -->
          <template v-if="!editingId">
            <el-divider content-position="left">租户管理员账号</el-divider>
            <el-form-item label="管理员邮箱" required><el-input v-model="form.adminEmail" placeholder="admin@example.com" /></el-form-item>
            <el-form-item label="管理员密码" required><el-input v-model="form.adminPassword" type="password" show-password placeholder="至少 6 位" /></el-form-item>
            <el-form-item label="管理员姓名"><el-input v-model="form.adminDisplayName" placeholder="可选，默认为邮箱前缀" /></el-form-item>
          </template>
        </template>
        <!-- 套餐表单：名称、说明、功能开关 JSON、额度限制 JSON、月/年费用（分） -->
        <template v-else-if="resource === 'plans'">
          <el-form-item label="套餐名称"><el-input v-model="form.name" /></el-form-item>
          <el-form-item label="说明"><el-input v-model="form.description" /></el-form-item>
          <el-form-item label="功能开关 JSON"><el-input v-model="form.featuresText" type="textarea" :rows="3" /></el-form-item>
          <el-form-item label="额度限制 JSON"><el-input v-model="form.limitsText" type="textarea" :rows="3" /></el-form-item>
          <el-form-item label="月费（分）"><el-input-number v-model="form.priceMonthly" :min="0" /></el-form-item>
          <el-form-item label="年费（分）"><el-input-number v-model="form.priceYearly" :min="0" /></el-form-item>
        </template>
        <!-- LLM 模型配置表单：名称、供应商、API Base/Key、模型名称、用途、定价 JSON -->
        <template v-else>
          <el-form-item label="配置名称"><el-input v-model="form.name" /></el-form-item>
          <el-form-item label="供应商"><el-input v-model="form.provider" /></el-form-item>
          <el-form-item label="API Base"><el-input v-model="form.apiBase" /></el-form-item>
          <el-form-item label="API Key"><el-input v-model="form.apiKey" type="password" show-password placeholder="编辑时留空表示不修改" /></el-form-item>
          <el-form-item label="模型名称"><el-input v-model="form.model" /></el-form-item>
          <el-form-item label="用途"><el-select v-model="form.purpose"><el-option label="对话" value="chat" /><el-option label="意图识别" value="intent" /><el-option label="向量化" value="embedding" /><el-option label="重排" value="rerank" /></el-select></el-form-item>
          <el-form-item label="定价 JSON"><el-input v-model="form.pricingText" type="textarea" :rows="3" /></el-form-item>
        </template>
        <!-- 通用：启用/停用开关 -->
        <el-form-item label="状态"><el-switch v-model="form.isActive" /></el-form-item>
      </el-form>
      <!-- 对话框底部按钮 -->
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" @click="save">保存</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.page-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
h2 { margin: 0; color: var(--text-strong); font-size: 22px; }
p { margin: 6px 0 0; color: var(--text-muted); font-size: 13px; }
</style>
