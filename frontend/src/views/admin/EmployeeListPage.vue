<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as employeesApi from '@/api/employees'
import * as rolesApi from '@/api/roles'
import type { EmployeeDetailResponse } from '@/api/employees'
import type { RoleDetailResponse } from '@/api/roles'
import OnlineStatusDot from '@/components/OnlineStatusDot.vue'
import RoleTag from '@/components/RoleTag.vue'
import EmployeeFormDialog from './EmployeeFormDialog.vue'

const employees = ref<EmployeeDetailResponse[]>([])
const roles = ref<RoleDetailResponse[]>([])
const loading = ref(true)
const dialogVisible = ref(false)
const editingEmployee = ref<EmployeeDetailResponse | null>(null)

async function loadData() {
  loading.value = true
  try {
    const [employeeList, roleList] = await Promise.all([
      employeesApi.getEmployees(),
      rolesApi.getRoles(),
    ])
    employees.value = employeeList
    roles.value = roleList
  } finally {
    loading.value = false
  }
}

onMounted(loadData)

function openCreate() {
  editingEmployee.value = null
  dialogVisible.value = true
}

function openEdit(employee: EmployeeDetailResponse) {
  editingEmployee.value = employee
  dialogVisible.value = true
}

async function handleDelete(employee: EmployeeDetailResponse) {
  try {
    await ElMessageBox.confirm(`确定要删除员工「${employee.displayName || employee.email}」吗？`, '确认删除', {
      type: 'warning',
    })
    await employeesApi.deleteEmployee(employee.id)
    ElMessage.success('员工已删除')
    await loadData()
  } catch {
    // 用户取消
  }
}

async function handleSubmit(data: {
  email: string
  password: string
  displayName: string | null
  phone: string | null
  skills: string[]
  maxConcurrentChats: number
  roleIds: string[]
}) {
  if (editingEmployee.value) {
    await employeesApi.updateEmployee(editingEmployee.value.id, {
      displayName: data.displayName,
      phone: data.phone,
      skills: data.skills,
      maxConcurrentChats: data.maxConcurrentChats,
    })
    await employeesApi.setEmployeeRoles(editingEmployee.value.id, { roleIds: data.roleIds })
    ElMessage.success('员工已更新')
  } else {
    const created = await employeesApi.createEmployee({
      email: data.email,
      password: data.password,
      displayName: data.displayName,
      phone: data.phone,
      skills: data.skills,
      maxConcurrentChats: data.maxConcurrentChats,
    })
    if (data.roleIds.length) {
      await employeesApi.setEmployeeRoles(created.id, { roleIds: data.roleIds })
    }
    ElMessage.success('员工已创建')
  }

  dialogVisible.value = false
  await loadData()
}
</script>

<template>
  <div class="page">
    <section class="page-header">
      <div>
        <p>团队管理</p>
        <h2>员工管理</h2>
      </div>
      <el-button type="primary" @click="openCreate">新建员工</el-button>
    </section>

    <section class="table-panel">
      <el-skeleton :loading="loading" animated>
        <template #default>
          <el-table v-if="employees.length" :data="employees">
            <el-table-column label="员工" min-width="220">
              <template #default="{ row }">
                <div class="employee-cell">
                  <el-avatar :size="34" :src="row.avatarUrl || undefined">
                    {{ (row.displayName || row.email).slice(0, 1).toUpperCase() }}
                  </el-avatar>
                  <div>
                    <strong>{{ row.displayName || '未命名' }}</strong>
                    <span>{{ row.email }}</span>
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <OnlineStatusDot :status="row.onlineStatus" />
              </template>
            </el-table-column>
            <el-table-column label="角色" min-width="220">
              <template #default="{ row }">
                <div class="tag-list">
                  <RoleTag v-for="role in row.roles" :key="role.id" :name="role.name" />
                  <span v-if="!row.roles.length" class="muted">未分配</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="技能" min-width="180">
              <template #default="{ row }">
                <div class="tag-list">
                  <el-tag v-for="skill in row.skills || []" :key="skill" size="small">{{ skill }}</el-tag>
                  <span v-if="!row.skills?.length" class="muted">未设置</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="maxConcurrentChats" label="会话上限" width="100" />
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="openEdit(row)">编辑</el-button>
                <el-button size="small" type="danger" plain @click="handleDelete(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="暂无员工" />
        </template>
      </el-skeleton>
    </section>

    <EmployeeFormDialog
      v-model:visible="dialogVisible"
      :employee="editingEmployee"
      :roles="roles"
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

.employee-cell {
  display: flex;
  align-items: center;
  gap: 12px;
}

.employee-cell strong,
.employee-cell span {
  display: block;
}

.employee-cell strong {
  color: var(--text-strong);
}

.employee-cell span,
.muted {
  color: var(--text-muted);
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
</style>
