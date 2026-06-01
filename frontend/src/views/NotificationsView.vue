<!--
  系统通知页面（NotificationsView）
  ===================================
  功能定位：集中展示平台推送的系统通知，包括人工接管提醒、敏感词触发告警、
  渠道异常通知和额度预警等。
  交互方式：
    - 页面挂载时自动加载通知列表
    - 点击"标为已读"按钮调用 API 标记单条通知已读，并刷新列表
    - 已读通知显示"已读"文字，不可重复标记
  注意：该页面无分页、无筛选，适合通知量较小的场景；若通知量大应考虑增加分页。
-->
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import * as api from '@/api/operations'

/** 表格加载状态 */
const loading = ref(false)
/** 通知列表数据 */
const items = ref<api.Notification[]>([])

/** 加载通知列表 */
async function loadData() {
  loading.value = true
  try { items.value = (await api.listNotifications()).items } finally { loading.value = false }
}

/**
 * 标记通知为已读
 * 仅当通知未读时调用 API 标记，已读通知不做重复请求
 * 操作后刷新整个列表以反映最新状态
 */
async function markRead(row: api.Notification) {
  if (!row.isRead) await api.markNotificationRead(row.id)
  await loadData()
}
// 组件挂载时加载通知列表
onMounted(loadData)
</script>

<template>
  <!-- 页面根容器 -->
  <section>
    <!-- 页面标题区：说明通知的来源类型 -->
    <h2>系统通知</h2>
    <p>人工接管、敏感词、渠道异常和额度预警会集中展示在这里。</p>
    <!-- 通知表格：标题、内容、等级、时间、已读状态 -->
    <el-table v-loading="loading" :data="items" stripe>
      <el-table-column prop="title" label="标题" min-width="180" />
      <el-table-column prop="content" label="内容" min-width="260" />
      <el-table-column prop="level" label="等级" width="90" />
      <el-table-column prop="createdAt" label="时间" width="180"><template #default="{ row }">{{ new Date(row.createdAt).toLocaleString() }}</template></el-table-column>
      <!-- 已读状态列：未读显示"标为已读"按钮，已读仅显示文字 -->
      <el-table-column label="状态" width="100"><template #default="{ row }"><el-button text type="primary" @click="markRead(row)">{{ row.isRead ? '已读' : '标为已读' }}</el-button></template></el-table-column>
    </el-table>
  </section>
</template>

<style scoped>h2{margin:0;color:var(--text-strong);font-size:22px}p{margin:6px 0 18px;color:var(--text-muted);font-size:13px}</style>
