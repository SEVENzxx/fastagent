<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import * as employeesApi from '@/api/employees'

const formRef = ref<FormInstance>()
const saving = ref(false)
const form = reactive({
  currentPassword: '',
  newPassword: '',
  confirmPassword: '',
})

const rules: FormRules = {
  currentPassword: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '新密码至少 6 位', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== form.newPassword) {
          callback(new Error('两次输入的新密码不一致'))
          return
        }
        callback()
      },
      trigger: 'blur',
    },
  ],
}

async function submit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  saving.value = true
  try {
    await employeesApi.changePassword({
      currentPassword: form.currentPassword,
      newPassword: form.newPassword,
    })
    form.currentPassword = ''
    form.newPassword = ''
    form.confirmPassword = ''
    ElMessage.success('密码已修改')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="settings-page">
    <header class="settings-header">
      <div>
        <p>账号设置</p>
        <h2>修改密码</h2>
      </div>
    </header>

    <section class="settings-grid">
      <aside class="hint-panel">
        <h3>安全建议</h3>
        <p>建议使用至少 8 位、包含字母和数字的密码。修改成功后，新密码会在下次登录时生效。</p>
      </aside>

      <section class="form-panel">
        <div class="section-title">
          <h3>密码验证</h3>
          <p>请先输入当前密码，再设置新的登录密码。</p>
        </div>

        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="password-form">
          <el-form-item label="当前密码" prop="currentPassword">
            <el-input v-model="form.currentPassword" type="password" show-password />
          </el-form-item>
          <el-form-item label="新密码" prop="newPassword">
            <el-input v-model="form.newPassword" type="password" show-password />
          </el-form-item>
          <el-form-item label="确认新密码" prop="confirmPassword">
            <el-input v-model="form.confirmPassword" type="password" show-password />
          </el-form-item>
          <el-button type="primary" :loading="saving" @click="submit">保存修改</el-button>
        </el-form>
      </section>
    </section>
  </div>
</template>

<style scoped>
.settings-page {
  max-width: 980px;
  display: grid;
  gap: 18px;
}

.settings-header,
.hint-panel,
.form-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.settings-header {
  padding: 22px;
}

.settings-header p,
.section-title p,
.hint-panel p {
  color: var(--text-muted);
}

.settings-header p {
  font-size: 13px;
  font-weight: 600;
}

.settings-header h2 {
  margin-top: 4px;
  color: var(--text-strong);
  font-size: 22px;
}

.settings-grid {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.hint-panel,
.form-panel {
  padding: 24px;
}

.hint-panel h3,
.section-title h3 {
  color: var(--text-strong);
  font-size: 18px;
}

.hint-panel p,
.section-title p {
  margin-top: 8px;
}

.section-title {
  margin-bottom: 20px;
}

.password-form {
  max-width: 520px;
}

@media (max-width: 860px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
}
</style>
