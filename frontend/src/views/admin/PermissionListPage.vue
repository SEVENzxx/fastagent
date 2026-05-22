<script setup lang="ts">
import { onMounted, ref } from 'vue'
import * as rolesApi from '@/api/roles'
import type { PermissionGroupedResponse } from '@/api/roles'

const groups = ref<PermissionGroupedResponse[]>([])
const loading = ref(true)

onMounted(async () => {
  try {
    groups.value = await rolesApi.getPermissions()
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="page">
    <section class="page-header">
      <div>
        <p>系统管理</p>
        <h2>权限码列表</h2>
      </div>
      <span class="header-note">按模块分组展示系统权限</span>
    </section>

    <el-skeleton :loading="loading" animated>
      <template #default>
        <div v-if="groups.length" class="module-grid">
          <section v-for="group in groups" :key="group.module" class="module-panel">
            <header>
              <div>
                <h3>{{ group.module }}</h3>
                <p>{{ group.permissions.length }} 个权限</p>
              </div>
            </header>
            <el-table :data="group.permissions" size="small">
              <el-table-column prop="code" label="权限码" min-width="200" />
              <el-table-column prop="name" label="名称" min-width="150" />
              <el-table-column prop="description" label="说明" min-width="220">
                <template #default="{ row }">
                  <span class="muted">{{ row.description || '未填写' }}</span>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </div>
        <el-empty v-else description="暂无权限码，请运行种子脚本" />
      </template>
    </el-skeleton>
  </div>
</template>

<style scoped>
.page {
  display: grid;
  gap: 18px;
}

.page-header,
.module-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 22px;
}

.page-header p,
.module-panel header p {
  color: var(--text-muted);
  font-size: 13px;
  font-weight: 600;
}

.page-header h2 {
  margin-top: 4px;
  color: var(--text-strong);
  font-size: 22px;
}

.header-note {
  color: var(--text-muted);
}

.module-grid {
  display: grid;
  gap: 16px;
}

.module-panel {
  overflow: hidden;
}

.module-panel header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-soft);
}

.module-panel h3 {
  color: var(--text-strong);
  font-size: 17px;
}

.module-panel header p {
  margin-top: 4px;
}

.muted {
  color: var(--text-muted);
}

@media (max-width: 700px) {
  .page-header {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
