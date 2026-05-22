<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import * as employeesApi from '@/api/employees'
import { useAuthStore } from '@/stores/useAuthStore'

const authStore = useAuthStore()
const loading = ref(true)
const saving = ref(false)

const form = reactive({
  email: '',
  displayName: '',
  avatarUrl: '',
  phone: '',
  skills: [] as string[],
})

async function loadProfile() {
  loading.value = true
  try {
    const profile = await employeesApi.getProfile()
    form.email = profile.email
    form.displayName = profile.displayName || ''
    form.avatarUrl = profile.avatarUrl || ''
    form.phone = profile.phone || ''
    form.skills = profile.skills || []
  } finally {
    loading.value = false
  }
}

async function saveProfile() {
  saving.value = true
  try {
    await employeesApi.updateProfile({
      displayName: form.displayName || null,
      avatarUrl: form.avatarUrl || null,
      phone: form.phone || null,
      skills: form.skills,
    })
    await authStore.fetchUser()
    ElMessage.success('个人资料已更新')
  } finally {
    saving.value = false
  }
}

onMounted(loadProfile)
</script>

<template>
  <div class="settings-page">
    <header class="settings-header">
      <div>
        <p>账号设置</p>
        <h2>个人资料</h2>
      </div>
      <el-button type="primary" :loading="saving" @click="saveProfile">保存修改</el-button>
    </header>

    <el-skeleton :loading="loading" animated>
      <template #default>
        <section class="settings-grid">
          <aside class="identity-panel">
            <el-avatar :size="80" :src="form.avatarUrl || undefined">
              {{ (form.displayName || form.email || 'U').slice(0, 1).toUpperCase() }}
            </el-avatar>
            <h3>{{ form.displayName || '未命名' }}</h3>
            <p>{{ form.email }}</p>
            <div class="skill-preview">
              <el-tag v-for="skill in form.skills" :key="skill" size="small" effect="plain">{{ skill }}</el-tag>
              <span v-if="!form.skills.length">暂无技能标签</span>
            </div>
          </aside>

          <section class="form-panel">
            <div class="section-title">
              <h3>基础信息</h3>
              <p>这些信息会用于工作台展示和团队协作。</p>
            </div>

            <el-form label-position="top" class="profile-form">
              <el-form-item label="邮箱">
                <el-input v-model="form.email" disabled />
              </el-form-item>
              <el-form-item label="姓名">
                <el-input v-model.trim="form.displayName" placeholder="显示名称" />
              </el-form-item>
              <el-form-item label="头像 URL">
                <el-input v-model.trim="form.avatarUrl" placeholder="https://..." />
              </el-form-item>
              <el-form-item label="手机号">
                <el-input v-model.trim="form.phone" placeholder="联系电话" />
              </el-form-item>
              <el-form-item label="技能标签">
                <el-select
                  v-model="form.skills"
                  multiple
                  filterable
                  allow-create
                  default-first-option
                  placeholder="添加技能"
                  class="full"
                >
                  <el-option v-for="skill in form.skills" :key="skill" :label="skill" :value="skill" />
                </el-select>
              </el-form-item>
            </el-form>
          </section>
        </section>
      </template>
    </el-skeleton>
  </div>
</template>

<style scoped>
.settings-page {
  max-width: 1080px;
  display: grid;
  gap: 18px;
}

.settings-header,
.identity-panel,
.form-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.settings-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 22px;
}

.settings-header p,
.section-title p {
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

.identity-panel {
  display: grid;
  justify-items: center;
  padding: 28px 22px;
  text-align: center;
}

.identity-panel h3 {
  margin-top: 14px;
  color: var(--text-strong);
  font-size: 20px;
}

.identity-panel p {
  margin-top: 4px;
  color: var(--text-muted);
}

.skill-preview {
  width: 100%;
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 18px;
  color: var(--text-muted);
}

.form-panel {
  padding: 24px;
}

.section-title {
  margin-bottom: 20px;
}

.section-title h3 {
  color: var(--text-strong);
  font-size: 18px;
}

.section-title p {
  margin-top: 4px;
}

.profile-form {
  max-width: 620px;
}

.full {
  width: 100%;
}

@media (max-width: 860px) {
  .settings-header {
    align-items: stretch;
    flex-direction: column;
  }

  .settings-grid {
    grid-template-columns: 1fr;
  }
}
</style>
