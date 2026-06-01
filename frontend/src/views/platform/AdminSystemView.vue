<script setup lang="ts">
/** 平台系统运维页面 — 系统设置 / 数据库监控 / 备份管理
 *
 *  权限：仅超管可访问（路由守卫处校验）。
 *  数据流：API 请求 → 组件本地状态 → 模板渲染。
 *  备份创建/恢复为异步操作，创建后自动刷新列表轮询状态。
 */
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as adminApi from '@/api/admin'

const activeTab = ref('settings')
const loading = ref(false)
const healthLoading = ref(false)
const backupLoading = ref(false)

// ── 系统设置 ──
interface SettingItem { key: string; value: string; description?: string | null }
const settingsMap = ref<Record<string, string>>({})
const settingItems = ref<SettingItem[]>([])

async function loadSettings() {
  loading.value = true
  try {
    const res = await adminApi.getSystemSettings()
    settingItems.value = res.settings
    const map: Record<string, string> = {}
    for (const item of res.settings) {
      map[item.key] = item.value
    }
    settingsMap.value = map
  } catch {
    ElMessage.error('加载系统设置失败')
  } finally {
    loading.value = false
  }
}

function getSetting(key: string, fallback: string = ''): string {
  return settingsMap.value[key] ?? fallback
}

function getSettingNumber(key: string, fallback: number): number {
  const v = settingsMap.value[key]
  return v ? Number(v) : fallback
}

function getSettingBool(key: string, fallback: boolean): boolean {
  const v = settingsMap.value[key]
  return v ? v === 'true' : fallback
}

async function saveSystemSettings() {
  try {
    await adminApi.updateSystemSettings({ settings: settingsMap.value })
    ElMessage.success('系统设置已保存')
  } catch {
    ElMessage.error('保存系统设置失败')
  }
}

function updateSetting(key: string, value: string) {
  settingsMap.value[key] = value
}

// ── 数据库健康 ──
const dbHealth = ref<adminApi.DbHealth>({
  activeConnections: 0,
  maxConnections: 100,
  dbSizeMb: 0,
  uptimeHours: 0,
  slowQueries24h: 0,
  indexHitRate: 0,
})

async function loadDbHealth() {
  healthLoading.value = true
  try {
    dbHealth.value = await adminApi.getDbHealth()
  } catch {
    ElMessage.error('加载数据库监控数据失败')
  } finally {
    healthLoading.value = false
  }
}

// ── 备份管理 ──
const backups = ref<adminApi.BackupRecord[]>([])
let backupPollTimer: ReturnType<typeof setInterval> | null = null

async function loadBackups() {
  backupLoading.value = true
  try {
    backups.value = await adminApi.listBackups()
  } catch {
    ElMessage.error('加载备份列表失败')
  } finally {
    backupLoading.value = false
  }
}

async function createBackup() {
  try {
    const result = await adminApi.createBackup('full')
    ElMessage.success(`备份任务已启动 (#${result.id})`)
    await loadBackups()
    startBackupPolling()
  } catch {
    ElMessage.error('创建备份失败')
  }
}

async function restoreBackup(id: string) {
  try {
    await ElMessageBox.confirm(
      '恢复操作会用备份数据覆盖当前数据库，确定要继续吗？',
      '高危操作确认',
      { confirmButtonText: '确认恢复', cancelButtonText: '取消', type: 'warning' }
    )
    await adminApi.restoreBackup(id)
    ElMessage.success('数据库恢复任务已启动')
  } catch {
    // 用户取消操作
  }
}

async function deleteBackup(id: string) {
  try {
    await ElMessageBox.confirm('确定要删除此备份吗？此操作不可撤销。', '确认删除', { type: 'warning' })
    await adminApi.deleteBackup(id)
    ElMessage.success('备份已删除')
    await loadBackups()
  } catch {
    // 用户取消操作
  }
}

// 当列表中有 running 状态的备份时，每 5 秒刷新一次
function startBackupPolling() {
  if (backupPollTimer) return
  backupPollTimer = setInterval(async () => {
    await loadBackups()
    const hasRunning = backups.value.some((b) => b.status === 'running')
    if (!hasRunning && backupPollTimer) {
      clearInterval(backupPollTimer)
      backupPollTimer = null
    }
  }, 5000)
}

onMounted(() => {
  loadSettings()
})

watch(() => activeTab.value, (tab) => {
  if (tab === 'db') loadDbHealth()
  else if (tab === 'backups') loadBackups()
})

onUnmounted(() => {
  if (backupPollTimer) {
    clearInterval(backupPollTimer)
    backupPollTimer = null
  }
})
</script>

<template>
  <section>
    <div class="page-header">
      <div>
        <h2>系统运维</h2>
        <p>平台级系统设置、数据库监控与备份恢复管理</p>
      </div>
    </div>

    <el-tabs v-model="activeTab">
      <!-- ═══ 系统设置 ═══ -->
      <el-tab-pane label="系统设置" name="settings">
        <el-card class="section-card" v-loading="loading">
          <template #header>全局参数</template>
          <el-form label-width="200px" label-position="left">
            <el-form-item v-for="item in settingItems" :key="item.key" :label="item.description || item.key">
              <!-- 布尔值用 switch -->
              <template v-if="getSetting(item.key) === 'true' || getSetting(item.key) === 'false'">
                <el-switch
                  :model-value="getSettingBool(item.key, false)"
                  @change="(v: boolean) => updateSetting(item.key, String(v))"
                />
              </template>
              <!-- 数字值用 input-number -->
              <template v-else-if="!isNaN(Number(getSetting(item.key))) && getSetting(item.key) !== ''">
                <el-input-number
                  :model-value="getSettingNumber(item.key, 0)"
                  @change="(v: number | undefined) => updateSetting(item.key, String(v ?? 0))"
                  :min="1" :max="10000"
                />
              </template>
              <!-- 其他值用 text input -->
              <template v-else>
                <el-input
                  :model-value="getSetting(item.key)"
                  @change="(v: string) => updateSetting(item.key, v)"
                />
              </template>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="saveSystemSettings">保存设置</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- ═══ 数据库监控 ═══ -->
      <el-tab-pane label="数据库监控" name="db">
        <div v-loading="healthLoading" class="metric-grid">
          <article class="metric-card">
            <span>活跃连接 / 上限</span>
            <strong>{{ dbHealth.activeConnections }} / {{ dbHealth.maxConnections }}</strong>
          </article>
          <article class="metric-card">
            <span>数据库大小</span>
            <strong>{{ dbHealth.dbSizeMb }} MB</strong>
          </article>
          <article class="metric-card">
            <span>运行时长</span>
            <strong>{{ dbHealth.uptimeHours }} 小时</strong>
          </article>
          <article class="metric-card">
            <span>24h 慢查询</span>
            <strong>{{ dbHealth.slowQueries24h }}</strong>
          </article>
          <article class="metric-card">
            <span>索引命中率</span>
            <strong>{{ dbHealth.indexHitRate }}%</strong>
          </article>
        </div>
        <el-divider />
        <el-alert type="info" :closable="false" show-icon
          title="数据来源"
          description="以上数据从 PostgreSQL 系统视图（pg_stat_activity / pg_database / pg_stat_user_tables）实时查询，反映当前数据库实际运行状态。" />
      </el-tab-pane>

      <!-- ═══ 备份管理 ═══ -->
      <el-tab-pane label="备份管理" name="backups">
        <div class="page-header sub-header">
          <span>备份列表</span>
          <el-button type="primary" @click="createBackup">创建备份</el-button>
        </div>
        <el-table :data="backups" stripe v-loading="backupLoading" empty-text="暂无备份记录">
          <el-table-column prop="name" label="备份名称" min-width="240" />
          <el-table-column prop="type" label="类型" width="80">
            <template #default="{ row }">
              <el-tag size="small" :type="row.type === 'full' ? 'primary' : 'info'">
                {{ row.type === 'full' ? '全量' : '结构' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="sizeMb" label="大小 (MB)" width="100" />
          <el-table-column prop="status" label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 'completed' ? 'success' : row.status === 'failed' ? 'danger' : 'warning'">
                {{ row.status === 'completed' ? '已完成' : row.status === 'running' ? '运行中' : '失败' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="createdAt" label="创建时间" width="180">
            <template #default="{ row }">{{ new Date(row.createdAt).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column label="操作" width="180">
            <template #default="{ row }">
              <el-button text type="primary" size="small"
                :disabled="row.status !== 'completed'"
                @click="restoreBackup(row.id)">恢复</el-button>
              <el-button text type="danger" size="small"
                @click="deleteBackup(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-divider />
        <el-alert type="warning" :closable="false" show-icon
          title="备份功能通过 pg_dump / pg_restore 执行"
          description="创建备份时 API 立即返回（status=running），后台异步执行 pg_dump。完成/失败后自动更新状态。恢复操作会清空当前数据库并用备份覆盖，请谨慎操作。" />
      </el-tab-pane>
    </el-tabs>
  </section>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}
.sub-header {
  margin-bottom: 12px;
}
h2 {
  margin: 0;
  color: var(--text-strong);
  font-size: 22px;
}
p {
  margin: 6px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}
.section-card {
  max-width: 720px;
}
.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 14px;
  margin-bottom: 10px;
}
.metric-card {
  min-height: 90px;
  display: grid;
  align-content: center;
  gap: 10px;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
}
.metric-card span {
  color: var(--text-muted);
  font-size: 13px;
}
.metric-card strong {
  color: var(--text-strong);
  font-size: 26px;
}
</style>
