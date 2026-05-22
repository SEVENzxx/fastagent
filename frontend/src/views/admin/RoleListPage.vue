<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as rolesApi from '@/api/roles'
import type { PermissionGroupedResponse, RoleDetailResponse } from '@/api/roles'
import RoleFormDialog from './RoleFormDialog.vue'

const roles = ref<RoleDetailResponse[]>([])
const permissionGroups = ref<PermissionGroupedResponse[]>([])
const loading = ref(true)
const dialogVisible = ref(false)
const editingRole = ref<RoleDetailResponse | null>(null)

async function loadData() {
  loading.value = true
  try {
    const [roleList, groups] = await Promise.all([rolesApi.getRoles(), rolesApi.getPermissions()])
    roles.value = roleList
    permissionGroups.value = groups
  } finally {
    loading.value = false
  }
}

onMounted(loadData)

function openCreate() {
  editingRole.value = null
  dialogVisible.value = true
}

function openEdit(role: RoleDetailResponse) {
  editingRole.value = role
  dialogVisible.value = true
}

async function handleDelete(role: RoleDetailResponse) {
  try {
    await ElMessageBox.confirm(`确定要删除角色「${role.name}」吗？`, '确认删除', { type: 'warning' })
    await rolesApi.deleteRole(role.id)
    ElMessage.success('角色已删除')
    await loadData()
  } catch {
    // 用户取消
  }
}

async function handleSubmit(data: { name: string; description: string | null; permissionIds: string[] }) {
  if (editingRole.value) {
    await rolesApi.updateRole(editingRole.value.id, { name: data.name, description: data.description })
    await rolesApi.setRolePermissions(editingRole.value.id, { permissionIds: data.permissionIds })
    ElMessage.success('角色已更新')
  } else {
    await rolesApi.createRole({
      name: data.name,
      description: data.description,
      permissionIds: data.permissionIds,
    })
    ElMessage.success('角色已创建')
  }
  await loadData()
}
</script>

<template>
  <div class="page">
    <section class="page-header">
      <div>
        <p>系统管理</p>
        <h2>角色管理</h2>
      </div>
      <el-button type="primary" @click="openCreate">新建角色</el-button>
    </section>

    <section class="table-panel">
      <el-skeleton :loading="loading" animated>
        <template #default>
          <el-table v-if="roles.length" :data="roles" class="role-table">
            <el-table-column prop="name" label="角色名称" min-width="150" />
            <el-table-column prop="description" label="描述" min-width="220">
              <template #default="{ row }">
                <span class="muted">{{ row.description || '未填写' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="权限" min-width="260">
              <template #default="{ row }">
                <div class="tag-list">
                  <el-tag v-for="perm in row.permissions" :key="perm.id" size="small" effect="plain">
                    {{ perm.name }}
                  </el-tag>
                  <span v-if="!row.permissions.length" class="muted">无权限</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="openEdit(row)">编辑</el-button>
                <el-button size="small" type="danger" plain @click="handleDelete(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="暂无角色" />
        </template>
      </el-skeleton>
    </section>

    <RoleFormDialog
      v-model:visible="dialogVisible"
      :role="editingRole"
      :permission-groups="permissionGroups"
      @submit="handleSubmit"
    />
  </div>
</template>

<style scoped>
.page {
  display: grid;
  gap: 18px;
}

.page-header,
.table-panel {
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

.page-header p {
  color: var(--text-muted);
  font-size: 13px;
  font-weight: 600;
}

.page-header h2 {
  margin-top: 4px;
  color: var(--text-strong);
  font-size: 22px;
}

.table-panel {
  padding: 8px 0;
  overflow: hidden;
}

.role-table {
  width: 100%;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.muted {
  color: var(--text-muted);
}

@media (max-width: 700px) {
  .page-header {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
