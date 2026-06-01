<!--
  审计与运营日志页面（AdminOperationsView）
  ===========================================
  功能定位：超级管理员专用的运营审计视图，展示平台级审计日志、登录历史和 LLM 用量。
  三个 Tab 分别展示：
    - audit: 审计日志（操作动作、资源类型、资源 ID、所属租户）
    - login: 登录历史（邮箱、成功/失败、失败原因）
    - usage: LLM 用量（租户 ID、来源、模型、Token 数、成本）
  数据特点：只追加记录（append-only），页面无删除操作，仅提供只读浏览。
-->
<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import * as api from '@/api/operations'
import * as usageApi from '@/api/usage'

/** 当前激活的 Tab */
const activeTab = ref('audit')
/** 表格加载状态 */
const loading = ref(false)
/** 表格数据列表 */
const items = ref<any[]>([])

/**
 * 加载数据：根据当前 Tab 调用不同的 API
 * - audit → listAuditLogs（审计日志）
 * - login → listLoginHistories（登录历史）
 * - usage → listAdminUsage（LLM 用量，跨租户聚合）
 */
async function loadData() {
  loading.value = true
  try {
    items.value = activeTab.value === 'audit'
      ? (await api.listAuditLogs()).items
      : activeTab.value === 'login'
        ? (await api.listLoginHistories()).items
        : (await usageApi.listAdminUsage()).items
  } finally { loading.value = false }
}
// 切换 Tab 时重新加载数据
watch(activeTab, loadData)
// 组件挂载时加载数据
onMounted(loadData)
</script>

<template>
  <!-- 页面根容器 -->
  <section>
    <!-- 页面标题区：说明数据为只追加记录，不可删除 -->
    <h2>审计与登录历史</h2>
    <p>平台关键操作和登录尝试只追加记录，不允许在页面中删除。</p>
    <!-- Tab 页签：审计日志 / 登录历史 / LLM 用量 -->
    <el-tabs v-model="activeTab"><el-tab-pane label="审计日志" name="audit" /><el-tab-pane label="登录历史" name="login" /><el-tab-pane label="LLM 用量" name="usage" /></el-tabs>
    <!--
      数据表格：根据 Tab 切换列配置
      所有 Tab 都显示"时间"列
    -->
    <el-table v-loading="loading" :data="items" stripe>
      <!-- 审计日志列：动作、资源类型、资源 ID、租户 ID -->
      <template v-if="activeTab === 'audit'">
        <el-table-column prop="action" label="动作" width="150" /><el-table-column prop="resourceType" label="资源" width="130" /><el-table-column prop="resourceId" label="资源 ID" min-width="170" /><el-table-column prop="tenantId" label="租户 ID" min-width="170" />
      </template>
      <!-- 登录历史列：邮箱、登录结果（成功/失败）、失败原因 -->
      <template v-else-if="activeTab === 'login'">
        <el-table-column prop="email" label="邮箱" min-width="220" /><el-table-column label="结果" width="90"><template #default="{ row }">{{ row.success ? '成功' : '失败' }}</template></el-table-column><el-table-column prop="failureReason" label="失败原因" min-width="160" />
      </template>
      <!-- LLM 用量列：租户 ID、来源、模型名称、Token 消耗、费用成本 -->
      <template v-else>
        <el-table-column prop="tenantId" label="租户 ID" min-width="170" /><el-table-column prop="source" label="来源" width="120" /><el-table-column prop="model" label="模型" min-width="160" /><el-table-column prop="totalTokens" label="Tokens" width="90" /><el-table-column prop="cost" label="成本" width="100" />
      </template>
      <!-- 通用列：记录时间，格式化为本地时间字符串 -->
      <el-table-column prop="createdAt" label="时间" width="180"><template #default="{ row }">{{ new Date(row.createdAt).toLocaleString() }}</template></el-table-column>
    </el-table>
  </section>
</template>

<style scoped>h2{margin:0;color:var(--text-strong);font-size:22px}p{margin:6px 0 12px;color:var(--text-muted);font-size:13px}</style>
