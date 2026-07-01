<!--
  跨租户业务管理页面（AdminBusinessView）
  ========================================
  功能定位：超级管理员只读运营视图，用于排障、审计和业务状态核查。
  三个 Tab 分别管理：
    - conversations: 跨租户会话列表，支持按租户/状态/关键词筛选，可查看会话消息详情
    - orders: 跨租户订单列表，支持按租户/状态筛选
    - knowledge: 知识库文档状态列表，支持按租户/状态筛选，可查看处理失败原因
  消息查看：点击会话行的"消息"按钮，通过 el-drawer 侧边栏展示该会话的所有消息
  交互特点：纯只读，无编辑/删除操作；切换 Tab 自动重置筛选条件
-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import * as adminApi from '@/api/admin'

/** 当前激活的 Tab 页签 */
const activeTab = ref('conversations')
/** 表格加载状态 */
const loading = ref(false)
/** 租户下拉选项列表（筛选条件） */
const tenants = ref<adminApi.Tenant[]>([])
/** 当前选中的租户筛选条件，null 表示全部租户 */
const tenantId = ref<string | null>(null)
/** 当前选中的状态筛选条件，null 表示全部状态 */
const status = ref<string | null>(null)
/** 关键词搜索（仅会话 Tab 使用，匹配客户名称或电话） */
const keyword = ref('')
/** 表格数据列表 */
const items = ref<Array<adminApi.AdminConversation | adminApi.AdminOrder | adminApi.AdminKnowledgeDoc>>([])
/** 数据总数（分页用） */
const total = ref(0)
/** 当前页码 */
const page = ref(1)
/** 每页条数 */
const pageSize = 20
/** 消息抽屉的显示状态 */
const drawerVisible = ref(false)
/** 消息列表加载状态 */
const messageLoading = ref(false)
/** 会话消息列表 */
const messages = ref<adminApi.AdminMessage[]>([])
/** 当前查看消息的会话记录 */
const selectedConversation = ref<adminApi.AdminConversation | null>(null)

/** 根据当前 Tab 动态计算页面标题 */
const title = computed(() => ({ conversations: '跨租户会话', orders: '跨租户订单', knowledge: '知识库状态' })[activeTab.value])

/**
 * 根据当前 Tab 动态返回状态筛选选项
 * 会话状态：AI处理中 → 待人工 → 人工处理中 → 已关闭
 * 订单状态：草稿 → 待客户确认 → 待审核发货 → 已发货 → 已签收 → 已取消
 * 知识库状态：处理中 → 就绪 → 失败
 */
const statusOptions = computed(() => activeTab.value === 'conversations'
  ? [['ai_processing', 'AI处理中'], ['pending_human', '待人工'], ['human_processing', '人工处理中'], ['closed', '已关闭']]
  : activeTab.value === 'orders'
    ? [['draft', '草稿'], ['pending_customer_confirm', '待客户确认'], ['customer_confirmed', '待审核发货'], ['shipped', '已发货'], ['signed', '已签收'], ['cancelled', '已取消']]
    : [['processing', '处理中'], ['ready', '就绪'], ['failed', '失败']])

/**
 * 加载表格数据：根据当前 Tab、筛选条件和分页参数调用对应的 API
 * 支持租户筛选（跨租户查看）、状态筛选、关键词搜索
 */
async function loadData() {
  loading.value = true
  try {
    const params = { tenant_id: tenantId.value || undefined, status: status.value || undefined, keyword: keyword.value || undefined, page: page.value, page_size: pageSize }
    const result = activeTab.value === 'conversations'
      ? await adminApi.listBusinessConversations(params)
      : activeTab.value === 'orders'
        ? await adminApi.listBusinessOrders(params)
        : await adminApi.listBusinessKnowledgeDocs(params)
    items.value = result.items
    total.value = result.total
  } finally {
    loading.value = false
  }
}

/**
 * 打开消息抽屉：加载指定会话的全部消息（最多 200 条）
 * 用于排障时查看客户与 AI/坐席的完整对话记录
 */
async function openMessages(row: adminApi.AdminConversation) {
  selectedConversation.value = row
  drawerVisible.value = true
  messageLoading.value = true
  try {
    messages.value = (await adminApi.listBusinessMessages(row.id, { page: 1, page_size: 200 })).items
  } finally {
    messageLoading.value = false
  }
}

/** 重置页码为第 1 页并重新加载数据 */
function resetAndLoad() {
  page.value = 1
  loadData()
}

// 切换 Tab 时：清空筛选条件并重新加载
watch(activeTab, () => {
  status.value = null
  keyword.value = ''
  resetAndLoad()
})
// 切换租户或状态筛选时：自动重新加载
watch([tenantId, status], resetAndLoad)

// 组件挂载时：加载租户列表（作为筛选下拉选项）和表格数据
onMounted(async () => {
  tenants.value = await adminApi.listTenants()
  await loadData()
})
</script>

<template>
  <!-- 页面根容器 -->
  <section>
    <!-- 页面标题区：说明本页用途为排障、审计和业务核查 -->
    <div class="page-header">
      <div><h2>跨租户业务管理</h2><p>只读运营视图，用于排障、审计和业务状态核查</p></div>
    </div>
    <!-- Tab 页签：会话 / 订单 / 知识库 -->
    <el-tabs v-model="activeTab">
      <el-tab-pane label="会话" name="conversations" />
      <el-tab-pane label="订单" name="orders" />
      <el-tab-pane label="知识库" name="knowledge" />
    </el-tabs>
    <!--
      筛选栏：租户下拉 → 状态下拉 → 关键词输入（仅会话 Tab）+ 查询按钮
      使用 grid 布局，切换 Tab 时自动重置筛选条件
    -->
    <div class="filters">
      <el-select v-model="tenantId" clearable placeholder="全部租户">
        <el-option v-for="item in tenants" :key="item.id" :label="item.name" :value="item.id" />
      </el-select>
      <el-select v-model="status" clearable placeholder="全部状态">
        <el-option v-for="[value, label] in statusOptions" :key="value" :label="label" :value="value" />
      </el-select>
      <el-input v-if="activeTab === 'conversations'" v-model="keyword" clearable placeholder="客户名称或电话" @keyup.enter="resetAndLoad" />
      <el-button v-if="activeTab === 'conversations'" type="primary" @click="resetAndLoad">查询</el-button>
    </div>

    <h3>{{ title }}</h3>
    <!--
      数据表格：根据激活 Tab 切换不同的业务列
      所有 Tab 都显示"租户"列和"创建时间"列
    -->
    <el-table v-loading="loading" :data="items" stripe>
      <el-table-column prop="tenantName" label="租户" min-width="140" />
      <!-- 会话 Tab 列：客户、坐席、状态、最近消息预览、查看消息按钮 -->
      <template v-if="activeTab === 'conversations'">
        <el-table-column prop="contactName" label="客户" min-width="140" />
        <el-table-column prop="employeeName" label="坐席" min-width="120" />
        <el-table-column prop="status" label="状态" width="140" />
        <el-table-column prop="lastMessagePreview" label="最近消息" min-width="220" show-overflow-tooltip />
        <el-table-column label="操作" width="90"><template #default="{ row }"><el-button text type="primary" @click="openMessages(row)">消息</el-button></template></el-table-column>
      </template>
      <!-- 订单 Tab 列：客户、状态、应付金额（¥格式化）、订单来源 -->
      <template v-else-if="activeTab === 'orders'">
        <el-table-column prop="contactName" label="客户" min-width="140" />
        <el-table-column prop="status" label="状态" width="150" />
        <el-table-column prop="payableAmount" label="应付金额" width="120"><template #default="{ row }">¥{{ row.payableAmount.toFixed(2) }}</template></el-table-column>
        <el-table-column prop="createdByType" label="来源" width="100" />
      </template>
      <!-- 知识库 Tab 列：文档标题、文件类型、处理状态、分块数、失败原因 -->
      <template v-else>
        <el-table-column prop="title" label="文档" min-width="220" />
        <el-table-column prop="fileType" label="类型" width="90" />
        <el-table-column prop="status" label="状态" width="100" />
        <el-table-column prop="chunkCount" label="分块数" width="90" />
        <el-table-column prop="errorMessage" label="失败原因" min-width="180" show-overflow-tooltip />
      </template>
      <!-- 通用列：创建时间，格式化为本地时间字符串 -->
      <el-table-column prop="createdAt" label="创建时间" width="180"><template #default="{ row }">{{ new Date(row.createdAt).toLocaleString() }}</template></el-table-column>
    </el-table>
    <!-- 分页器 -->
    <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="total, prev, pager, next" class="pagination" @current-change="loadData" />

    <!--
      消息查看抽屉（el-drawer）：从右侧滑出，展示会话的完整消息列表
      每条消息显示发送者类型、时间、内容（撤回消息显示"消息已撤回"）
    -->
    <el-drawer v-model="drawerVisible" :title="`会话消息 · ${selectedConversation?.contactName || ''}`" size="520px">
      <div v-loading="messageLoading" class="message-list">
        <div v-for="message in messages" :key="message.id" class="message-row">
          <div><strong>{{ message.senderType }}</strong><time>{{ new Date(message.createdAt).toLocaleString() }}</time></div>
          <p>{{ message.isRecalled ? '消息已撤回' : message.content }}</p>
        </div>
      </div>
    </el-drawer>
  </section>
</template>

<style scoped>
.page-header { margin-bottom: 12px; }
h2 { margin: 0; color: var(--text-strong); font-size: 22px; }
h3 { margin: 18px 0 12px; color: var(--text-strong); font-size: 16px; }
.page-header p { margin: 6px 0 0; color: var(--text-muted); font-size: 13px; }
.filters { display: grid; grid-template-columns: 220px 180px minmax(180px, 320px) auto; gap: 10px; align-items: center; }
.pagination { justify-content: center; margin-top: 16px; }
.message-list { display: grid; gap: 10px; }
.message-row { padding: 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); }
.message-row div { display: flex; justify-content: space-between; gap: 10px; color: var(--text-muted); font-size: 12px; }
.message-row strong { color: var(--text-strong); }
.message-row p { margin: 8px 0 0; color: var(--text); white-space: pre-wrap; overflow-wrap: anywhere; }
@media (max-width: 900px) { .filters { grid-template-columns: 1fr; } }
</style>
