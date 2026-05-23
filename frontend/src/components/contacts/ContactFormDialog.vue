<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { reactive, ref, watch } from 'vue'
import type { EmployeeDetailResponse } from '@/api/employees'
import type { ContactCreate, ContactResponse, ContactUpdate } from '@/api/contacts'

const props = defineProps<{
  visible: boolean
  contact?: ContactResponse | null
  employees?: EmployeeDetailResponse[]
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  submit: [data: ContactCreate | ContactUpdate]
}>()

const formRef = ref()
const submitting = ref(false)

const form = reactive({
  name: '',
  avatarUrl: '',
  phone: '',
  address: '',
  tags: [] as string[],
  assignedEmployeeId: null as string | null,
  externalIdsText: '',
})

const rules = {
  name: [
    { required: true, message: '请输入联系人名称', trigger: 'blur' },
    { max: 200, message: '联系人名称不能超过200个字符', trigger: 'blur' },
  ],
  phone: [{ max: 20, message: '电话不能超过20个字符', trigger: 'blur' }],
  avatarUrl: [{ max: 500, message: '头像地址不能超过500个字符', trigger: 'blur' }],
}

watch(
  () => props.visible,
  (visible) => {
    if (!visible) return
    const contact = props.contact
    form.name = contact?.name ?? ''
    form.avatarUrl = contact?.avatarUrl ?? ''
    form.phone = contact?.phone ?? ''
    form.address = contact?.address ?? ''
    form.tags = contact?.tags ? [...contact.tags] : []
    form.assignedEmployeeId = contact?.assignedEmployeeId ?? null
    form.externalIdsText = contact?.externalIds
      ? JSON.stringify(contact.externalIds, null, 2)
      : ''
  },
)

async function handleSubmit() {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }

  let externalIds: Record<string, any> | null = null
  if (form.externalIdsText.trim()) {
    try {
      externalIds = JSON.parse(form.externalIdsText)
    } catch {
      ElMessage.warning('外部 ID JSON 格式不正确')
      return
    }
  }

  submitting.value = true
  emit('submit', {
    name: form.name.trim(),
    avatarUrl: form.avatarUrl.trim() || undefined,
    phone: form.phone.trim() || undefined,
    address: form.address.trim() || undefined,
    tags: form.tags,
    assignedEmployeeId: form.assignedEmployeeId || null,
    externalIds,
  })
  submitting.value = false
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="contact ? '编辑联系人' : '新增联系人'"
    width="680px"
    destroy-on-close
    @update:model-value="emit('update:visible', $event)"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
      <el-row :gutter="16">
        <el-col :span="14">
          <el-form-item label="联系人名称" prop="name" required>
            <el-input v-model="form.name" maxlength="200" placeholder="请输入联系人名称" />
          </el-form-item>
        </el-col>
        <el-col :span="10">
          <el-form-item label="电话" prop="phone">
            <el-input v-model="form.phone" maxlength="20" placeholder="手机号或座机" />
          </el-form-item>
        </el-col>
      </el-row>

      <el-form-item label="分配员工">
        <el-select
          v-model="form.assignedEmployeeId"
          placeholder="未分配"
          clearable
          style="width: 100%"
        >
          <el-option
            v-for="employee in employees"
            :key="employee.id"
            :label="employee.displayName || employee.email"
            :value="employee.id"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="标签">
        <el-select
          v-model="form.tags"
          multiple
          filterable
          allow-create
          default-first-option
          placeholder="输入标签后回车"
          style="width: 100%"
        />
      </el-form-item>

      <el-form-item label="头像地址" prop="avatarUrl">
        <el-input v-model="form.avatarUrl" maxlength="500" placeholder="企业微信头像 URL" />
      </el-form-item>

      <el-form-item label="地址">
        <el-input v-model="form.address" type="textarea" :rows="2" placeholder="客户地址" />
      </el-form-item>

      <el-form-item label="外部 ID (JSON)">
        <el-input
          v-model="form.externalIdsText"
          type="textarea"
          :rows="3"
          placeholder='{"wecom_external_userid": "wmxxxxxxxxxxxxxx"}'
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="handleSubmit">保存</el-button>
    </template>
  </el-dialog>
</template>
