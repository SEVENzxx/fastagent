<!--
  平台总览看板页面（AdminDashboardView）
  ========================================
  功能定位：超级管理员登录后的首页，展示全平台核心指标的聚合概览。
  数据来源：调用 GET /admin/dashboard 接口，返回跨租户的统计汇总。
  展示指标：租户总数、启用租户数、套餐数量、模型配置数、会话总数、订单总数。
  交互方式：纯展示页面，无编辑操作，页面挂载时自动加载数据。
-->
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import * as adminApi from '@/api/admin'

/** 页面加载状态，用于控制 el-table / el-card 的 v-loading 指令 */
const loading = ref(true)
/** 平台看板聚合数据，由后端 /admin/dashboard 接口返回 */
const data = ref<adminApi.AdminDashboard | null>(null)

// 组件挂载后自动请求平台看板数据
onMounted(async () => {
  try {
    data.value = await adminApi.getDashboard()
  } finally {
    loading.value = false
  }
})

/**
 * 指标卡片定义
 * key: 对应 AdminDashboard 接口返回的字段名
 * label: 中文展示名称
 * 使用 as const 确保遍历时的类型安全
 */
const metrics = [
  ['tenantCount', '租户总数'],
  ['activeTenantCount', '启用租户'],
  ['planCount', '套餐数量'],
  ['llmConfigCount', '模型配置'],
  ['conversationCount', '会话总数'],
  ['orderCount', '订单总数'],
] as const
</script>

<template>
  <!-- 页面根容器 -->
  <section>
    <!-- 页面标题区：左侧标题 + 描述，右侧无操作按钮（纯展示页） -->
    <div class="page-header">
      <div>
        <h2>平台总览</h2>
        <p>租户、模型池与核心业务数据概览</p>
      </div>
    </div>
    <!-- 指标卡片网格：auto-fit 自适应列数，最小列宽 180px -->
    <div v-loading="loading" class="metric-grid">
      <article v-for="[key, label] in metrics" :key="key" class="metric-card">
        <span>{{ label }}</span>
        <!-- 数值大号展示，无数据时显示 0 -->
        <strong>{{ data?.[key] ?? 0 }}</strong>
      </article>
    </div>
  </section>
</template>

<style scoped>
.page-header { margin-bottom: 18px; }
h2 { margin: 0; color: var(--text-strong); font-size: 22px; }
p { margin: 6px 0 0; color: var(--text-muted); font-size: 13px; }
.metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; }
.metric-card { min-height: 112px; display: grid; align-content: center; gap: 12px; padding: 18px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); }
.metric-card span { color: var(--text-muted); font-size: 13px; }
.metric-card strong { color: var(--text-strong); font-size: 30px; }
</style>
