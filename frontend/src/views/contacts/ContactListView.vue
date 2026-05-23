<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as contactsApi from '@/api/contacts'
import * as employeesApi from '@/api/employees'
import type { ContactCreate, ContactResponse, ContactTagAggregate, ContactUpdate } from '@/api/contacts'
import type { EmployeeDetailResponse } from '@/api/employees'
import ContactFormDialog from '@/components/contacts/ContactFormDialog.vue'
import ContactImportDialog from '@/components/contacts/ContactImportDialog.vue'

const router = useRouter()

const contacts = ref<ContactResponse[]>([])
const employees = ref<EmployeeDetailResponse[]>([])
const tagOptions = ref<ContactTagAggregate[]>([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

const keyword = ref('')
const selectedTag = ref<string | null>(null)
const selectedEmployeeId = ref<string | null>(null)

const dialogVisible = ref(false)
const importDialogVisible = ref(false)
const editingContact = ref<ContactResponse | null>(null)

async function loadEmployees() {
  try {
    employees.value = await employeesApi.getEmployees()
  } catch {
    employees.value = []
  }
}

async function loadTags() {
  tagOptions.value = await contactsApi.getContactTags()
}

async function loadData() {
  loading.value = true
  try {
    const result = await contactsApi.getContacts({
      keyword: keyword.value || undefined,
      tag: selectedTag.value || undefined,
      assignedEmployeeId: selectedEmployeeId.value || undefined,
      page: page.value,
      pageSize: pageSize.value,
    })
    contacts.value = result.items
    total.value = result.total
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
  loadData()
}

function openCreate() {
  editingContact.value = null
  dialogVisible.value = true
}

function openImport() {
  importDialogVisible.value = true
}

function openEdit(contact: ContactResponse) {
  editingContact.value = contact
  dialogVisible.value = true
}

async function handleSubmit(data: ContactCreate | ContactUpdate) {
  try {
    if (editingContact.value) {
      await contactsApi.updateContact(editingContact.value.id, data as ContactUpdate)
      ElMessage.success('联系人已更新')
    } else {
      await contactsApi.createContact(data as ContactCreate)
      ElMessage.success('联系人已创建')
    }
    dialogVisible.value = false
    await Promise.all([loadData(), loadTags()])
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '联系人保存失败')
  }
}

async function handleImported() {
  await Promise.all([loadData(), loadTags()])
}

async function handleAssign(contact: ContactResponse, employeeId: string | null) {
  try {
    await contactsApi.assignContact(contact.id, employeeId)
    ElMessage.success(employeeId ? '联系人已分配' : '已取消分配')
    await loadData()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '分配失败')
  }
}

async function handleDelete(contact: ContactResponse) {
  try {
    await ElMessageBox.confirm(`确定删除联系人「${contact.name}」吗？`, '确认删除', {
      type: 'warning',
    })
    await contactsApi.deleteContact(contact.id)
    ElMessage.success('联系人已删除')
    await Promise.all([loadData(), loadTags()])
  } catch {
    /* cancelled */
  }
}

function goDetail(contact: ContactResponse) {
  router.push(`/contacts/${contact.id}`)
}

onMounted(async () => {
  await Promise.all([loadEmployees(), loadTags(), loadData()])
})
</script>

<template>
  <div class="page">
    <section class="page-header">
      <div>
        <p>客户资产</p>
        <h2>联系人管理</h2>
      </div>
      <div class="header-actions">
        <el-button @click="openImport">批量导入</el-button>
        <el-button type="primary" @click="openCreate">新增联系人</el-button>
      </div>
    </section>

    <section class="filter-bar">
      <el-input
        v-model="keyword"
        placeholder="搜索名称 / 电话 / 地址"
        clearable
        style="width: 280px"
        @keyup.enter="onSearch"
        @clear="onSearch"
      />
      <el-select
        v-model="selectedTag"
        placeholder="全部标签"
        clearable
        style="width: 180px"
        @change="onSearch"
      >
        <el-option
          v-for="item in tagOptions"
          :key="item.tag"
          :label="`${item.tag} (${item.count})`"
          :value="item.tag"
        />
      </el-select>
      <el-select
        v-model="selectedEmployeeId"
        placeholder="全部员工"
        clearable
        style="width: 200px"
        @change="onSearch"
      >
        <el-option
          v-for="employee in employees"
          :key="employee.id"
          :label="employee.displayName || employee.email"
          :value="employee.id"
        />
      </el-select>
      <el-button @click="onSearch">搜索</el-button>
    </section>

    <section class="table-panel">
      <el-table :data="contacts" v-loading="loading" row-key="id" border>
        <el-table-column label="客户" min-width="210">
          <template #default="{ row }">
            <button class="contact-cell" type="button" @click="goDetail(row)">
              <el-avatar :size="34" :src="row.avatarUrl || undefined">
                {{ row.name.slice(0, 1) }}
              </el-avatar>
              <span>{{ row.name }}</span>
            </button>
          </template>
        </el-table-column>
        <el-table-column prop="phone" label="电话" width="150" />
        <el-table-column label="标签" min-width="200">
          <template #default="{ row }">
            <div class="tag-list">
              <el-tag v-for="tag in row.tags" :key="tag" size="small" effect="plain">
                {{ tag }}
              </el-tag>
              <span v-if="!row.tags.length" class="muted">无</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="分配员工" width="220">
          <template #default="{ row }">
            <el-select
              :model-value="row.assignedEmployeeId"
              placeholder="未分配"
              clearable
              @change="(value: string | null) => handleAssign(row, value)"
            >
              <el-option
                v-for="employee in employees"
                :key="employee.id"
                :label="employee.displayName || employee.email"
                :value="employee.id"
              />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column prop="address" label="地址" min-width="220" show-overflow-tooltip />
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" plain @click="handleDelete(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="prev, pager, next, total"
        background
        class="pagination"
        @current-change="loadData"
      />
    </section>

    <ContactFormDialog
      v-model:visible="dialogVisible"
      :contact="editingContact"
      :employees="employees"
      @submit="handleSubmit"
    />

    <ContactImportDialog
      v-model:visible="importDialogVisible"
      @imported="handleImported"
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

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.table-panel {
  padding: 18px;
}

.contact-cell {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  border: 0;
  background: transparent;
  color: var(--primary);
  cursor: pointer;
  font-weight: 600;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.muted {
  color: var(--text-muted);
}

.pagination {
  margin-top: 18px;
  justify-content: center;
}
</style>
