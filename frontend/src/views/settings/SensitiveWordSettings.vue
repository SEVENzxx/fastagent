<!--
  敏感词管理页面（SensitiveWordSettings）
  =========================================
  功能定位：配置平台级敏感词规则，与租户级规则同时生效，用于内容安全审核。
  触发场景：当 AI 生成回复或客户发送消息命中敏感词时，根据配置的动作执行：
    - block: 拦截消息并转人工处理
    - transfer: 转人工审核
    - warn: 仅告警记录，不阻断流程
  操作支持：
    - 新增：输入敏感词 + 选择处理动作，默认启用
    - 启用/停用：通过 toggle 按钮切换敏感词规则的生效状态（不删除记录，避免误操作导致数据丢失）
  注意：本页面无编辑功能（新增后只能启用/停用），如需修改敏感词需删除后重新添加。
-->
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import * as api from '@/api/operations'

/** 表格加载状态 */
const loading = ref(false)
/** 敏感词列表 */
const items = ref<api.SensitiveWord[]>([])
/** 新增敏感词对话框的显示状态 */
const dialogVisible = ref(false)
/** 新增敏感词表单，默认处理动作为"仅告警"、默认启用 */
const form = ref({ word: '', action: 'warn' as api.SensitiveWord['action'], isActive: true })

/** 加载敏感词列表 */
async function loadData() {
  loading.value = true
  try { items.value = await api.listSensitiveWords() } finally { loading.value = false }
}

/**
 * 保存新增敏感词
 * 成功后关闭对话框、重置表单、刷新列表
 */
async function save() {
  await api.createSensitiveWord(form.value)
  dialogVisible.value = false
  form.value = { word: '', action: 'warn', isActive: true }
  ElMessage.success('敏感词已保存')
  await loadData()
}

/**
 * 切换敏感词启用/停用状态
 * 仅更新 isActive 字段，不删除记录
 */
async function toggle(row: api.SensitiveWord) {
  await api.updateSensitiveWord(row.id, { isActive: !row.isActive })
  await loadData()
}

// 组件挂载时加载敏感词列表
onMounted(loadData)
</script>

<template>
  <!-- 页面根容器 -->
  <section>
    <!-- 页面标题区：左侧标题 + 说明，右侧新增按钮 -->
    <div class="header"><div><h2>敏感词管理</h2><p>租户规则会与平台通用规则同时生效。</p></div><el-button type="primary" @click="dialogVisible = true">新增敏感词</el-button></div>
    <!-- 敏感词表格：敏感词内容、处理动作、启用/停用状态、操作按钮 -->
    <el-table v-loading="loading" :data="items" stripe>
      <el-table-column prop="word" label="敏感词" min-width="180" />
      <el-table-column prop="action" label="处理动作" width="140" />
      <!-- 状态列：启用=绿色标签，停用=灰色标签 -->
      <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.isActive ? 'success' : 'info'">{{ row.isActive ? '启用' : '停用' }}</el-tag></template></el-table-column>
      <!-- 操作列：切换启用/停用状态 -->
      <el-table-column label="操作" width="100"><template #default="{ row }"><el-button text type="primary" @click="toggle(row)">{{ row.isActive ? '停用' : '启用' }}</el-button></template></el-table-column>
    </el-table>
    <!-- 新增敏感词对话框 -->
    <el-dialog v-model="dialogVisible" title="新增敏感词" width="460px">
      <el-form label-position="top">
        <el-form-item label="敏感词"><el-input v-model="form.word" /></el-form-item>
        <!--
          处理动作下拉框：
          - block: 拦截消息并转人工
          - transfer: 转人工审核
          - warn: 仅告警记录，不阻断
        -->
        <el-form-item label="处理动作"><el-select v-model="form.action"><el-option label="拦截并转人工" value="block" /><el-option label="转人工审核" value="transfer" /><el-option label="仅告警记录" value="warn" /></el-select></el-form-item>
      </el-form>
      <!-- 对话框底部按钮 -->
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" @click="save">保存</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.header { display:flex; justify-content:space-between; gap:16px; margin-bottom:18px; }
h2 { margin:0; font-size:22px; color:var(--text-strong); } p { margin:6px 0 0; color:var(--text-muted); font-size:13px; }
</style>
