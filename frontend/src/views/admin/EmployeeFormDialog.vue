<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import type { EmployeeDetailResponse } from '@/api/employees'
import type { RoleDetailResponse } from '@/api/roles'

const props = defineProps<{
  visible: boolean
  employee?: EmployeeDetailResponse | null
  roles: RoleDetailResponse[]
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  submit: [data: {
    email: string
    password: string
    displayName: string | null
    phone: string | null
    skills: string[]
    maxConcurrentChats: number
    roleIds: string[]
  }]
}>()

const formRef = ref<FormInstance>()
const form = reactive({
  email: '',
  password: '',
  displayName: '',
  phone: '',
  skills: [] as string[],
  maxConcurrentChats: 10,
  roleIds: [] as string[],
})

const isEdit = () => !!props.employee

const rules: FormRules = {
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
  password: [{ required: true, message: '请输入初始密码', trigger: 'blur' }],
  displayName: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
}

watch(
  () => props.visible,
  (visible) => {
    if (!visible) return

    if (props.employee) {
      form.email = props.employee.email
      form.password = ''
      form.displayName = props.employee.displayName || ''
      form.phone = props.employee.phone || ''
      form.skills = props.employee.skills || []
      form.maxConcurrentChats = props.employee.maxConcurrentChats
      form.roleIds = props.employee.roles.map((role) => role.id)
      return
    }

    form.email = ''
    form.password = ''
    form.displayName = ''
    form.phone = ''
    form.skills = []
    form.maxConcurrentChats = 10
    form.roleIds = []
  },
)

function close() {
  emit('update:visible', false)
}

async function submit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  emit('submit', {
    email: form.email,
    password: form.password,
    displayName: form.displayName || null,
    phone: form.phone || null,
    skills: form.skills,
    maxConcurrentChats: form.maxConcurrentChats,
    roleIds: form.roleIds,
  })
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="isEdit() ? '编辑员工' : '新建员工'"
    width="640px"
    destroy-on-close
    @update:model-value="emit('update:visible', $event)"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
      <el-form-item label="邮箱" prop="email">
        <el-input v-model.trim="form.email" :disabled="isEdit()" placeholder="name@example.com" />
      </el-form-item>
      <el-form-item v-if="!isEdit()" label="初始密码" prop="password">
        <el-input v-model="form.password" type="password" show-password placeholder="至少 6 位" />
      </el-form-item>
      <el-form-item label="姓名" prop="displayName">
        <el-input v-model.trim="form.displayName" placeholder="员工姓名" />
      </el-form-item>
      <el-form-item label="手机号">
        <el-input v-model.trim="form.phone" placeholder="联系电话" />
      </el-form-item>
      <el-form-item label="技能标签">
        <el-select v-model="form.skills" multiple filterable allow-create default-first-option placeholder="添加技能">
          <el-option v-for="skill in form.skills" :key="skill" :label="skill" :value="skill" />
        </el-select>
      </el-form-item>
      <el-form-item label="最大同时会话数">
        <el-input-number v-model="form.maxConcurrentChats" :min="1" :max="200" />
      </el-form-item>
      <el-form-item label="角色">
        <el-select v-model="form.roleIds" multiple placeholder="选择角色" class="full">
          <el-option v-for="role in roles" :key="role.id" :label="role.name" :value="role.id" />
        </el-select>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" @click="submit">{{ isEdit() ? '保存' : '创建' }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.full {
  width: 100%;
}
</style>
