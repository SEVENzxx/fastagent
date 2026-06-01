<!--
  租户数据看板页面（TenantDashboardView）
  ========================================
  功能定位：面向单个租户的数据概览，展示本租户的核心业务量、模型消耗和套餐限制。
  数据来源：调用 GET /usage/dashboard 接口（租户级，自动带租户隔离），
  返回当前租户的会话数、消息数、订单数、知识文档数、图片素材数、LLM Token 消耗、
  累计成本及套餐额度限制。
  展示区域：
    1. 指标卡片网格：6 个核心业务指标
    2. 模型成本卡片：累计 LLM 调用费用（精确到小数点后 6 位）
    3. 套餐额度卡片：以 JSON 格式展示当前套餐的功能开关和用量限制
  交互方式：纯展示页面，无编辑操作，页面挂载时自动加载数据。
-->
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import * as api from '@/api/usage'

/** 页面加载状态，用于控制卡片区域的 v-loading 指令 */
const loading = ref(true)
/** 租户看板数据，由后端 /usage/dashboard 接口返回（自带租户隔离） */
const data = ref<api.TenantDashboard | null>(null)

/**
 * 核心业务指标定义
 * key: 对应 TenantDashboard 接口返回的字段名
 * label: 中文展示名称
 */
const metrics = [
  ['conversationCount', '会话数'], ['messageCount', '消息数'], ['orderCount', '订单数'],
  ['knowledgeDocCount', '知识文档'], ['imageCount', '图片素材'], ['llmTotalTokens', 'LLM Tokens'],
] as const

// 组件挂载后自动请求租户看板数据
onMounted(async () => { try { data.value = await api.getDashboard() } finally { loading.value = false } })
</script>
<template>
  <!-- 页面根容器 -->
  <section>
    <!-- 页面标题区 -->
    <h2>数据看板</h2>
    <p>展示本租户核心业务量、模型消耗和当前套餐限制。</p>
    <!-- 指标卡片网格：6 个核心业务指标，auto-fit 自适应列宽 -->
    <div v-loading="loading" class="grid">
      <article v-for="[key,label] in metrics" :key="key">
        <span>{{ label }}</span>
        <!-- 数值大号展示，无数据时显示 0 -->
        <strong>{{ data?.[key] ?? 0 }}</strong>
      </article>
    </div>
    <!-- 模型成本卡片：展示 LLM 调用的累计费用 -->
    <el-card class="cost">
      <template #header>模型成本</template>
      累计成本：¥{{ (data?.llmTotalCost ?? 0).toFixed(6) }}
    </el-card>
    <!-- 套餐额度卡片：以格式化 JSON 展示当前套餐的限制配置 -->
    <el-card>
      <template #header>套餐额度</template>
      <pre>{{ JSON.stringify(data?.planLimits ?? {}, null, 2) }}</pre>
    </el-card>
  </section>
</template>
<style scoped>h2{margin:0;color:var(--text-strong);font-size:22px}p{margin:6px 0 18px;color:var(--text-muted);font-size:13px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:14px}article{display:grid;gap:10px;padding:16px;border:1px solid var(--border);border-radius:8px;background:var(--surface)}span{color:var(--text-muted);font-size:13px}strong{font-size:27px;color:var(--text-strong)}.cost{margin-bottom:14px}pre{margin:0;white-space:pre-wrap}</style>
