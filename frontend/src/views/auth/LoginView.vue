<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { isAxiosError } from 'axios'
import { useAuthStore } from '@/stores/useAuthStore'

interface LoginForm {
  email: string
  password: string
}

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const errorMessage = ref('')
const form = reactive<LoginForm>({
  email: '',
  password: '',
})

const rules: FormRules<LoginForm> = {
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
  ],
}

function getErrorMessage(error: unknown) {
  if (isAxiosError(error)) {
    return error.response?.data?.detail ?? '邮箱或密码错误'
  }
  return '登录失败，请稍后重试'
}

async function handleLogin() {
  if (!formRef.value) return

  errorMessage.value = ''
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await authStore.login(form.email, form.password)
    ElMessage.success('登录成功')

    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    await router.push(redirect)
  } catch (error) {
    errorMessage.value = getErrorMessage(error)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-hero">
      <div class="brand-line">
        <span>FA</span>
        <strong>FastAgent</strong>
      </div>
      <h1>登录控制台</h1>
      <p>进入后台管理角色、权限和系统配置。</p>
    </section>

    <section class="auth-panel">
      <div class="panel-heading">
        <h2>欢迎回来</h2>
        <p>使用你的账号继续访问。</p>
      </div>

      <el-alert
        v-if="errorMessage"
        class="auth-error"
        :title="errorMessage"
        type="error"
        show-icon
        :closable="false"
      />

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="handleLogin">
        <el-form-item label="邮箱" prop="email">
          <el-input v-model.trim="form.email" autocomplete="email" placeholder="name@example.com" />
        </el-form-item>

        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            autocomplete="current-password"
            placeholder="请输入密码"
            show-password
          />
        </el-form-item>

        <el-button class="submit-button" type="primary" native-type="submit" :loading="loading">
          登录
        </el-button>
      </el-form>

      <p class="auth-switch">
        账号由平台管理员创建，如需开通请联系超级管理员。
      </p>
    </section>
  </main>
</template>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(320px, 1fr) minmax(360px, 480px);
  background: var(--app-bg);
}

.auth-hero {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 56px;
  color: #fff;
  background:
    linear-gradient(135deg, rgba(15, 23, 42, 0.92), rgba(30, 64, 175, 0.86)),
    url('/src/assets/hero.png') center / cover;
}

.brand-line {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 44px;
}

.brand-line span {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: #fff;
  color: var(--primary);
  font-weight: 800;
}

.auth-hero h1 {
  max-width: 520px;
  font-size: 40px;
  line-height: 1.15;
}

.auth-hero p {
  max-width: 460px;
  margin-top: 14px;
  color: rgba(255, 255, 255, 0.78);
  font-size: 16px;
}

.auth-panel {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 56px;
  background: var(--surface);
}

.panel-heading {
  margin-bottom: 26px;
}

.panel-heading h2 {
  color: var(--text-strong);
  font-size: 26px;
}

.panel-heading p {
  margin-top: 8px;
  color: var(--text-muted);
}

.auth-error {
  margin-bottom: 18px;
}

.submit-button {
  width: 100%;
  height: 42px;
  margin-top: 6px;
}

.auth-switch {
  margin-top: 22px;
  text-align: center;
  color: var(--text-muted);
}

@media (max-width: 820px) {
  .auth-page {
    grid-template-columns: 1fr;
  }

  .auth-hero {
    min-height: 240px;
    padding: 36px 24px;
  }

  .brand-line {
    margin-bottom: 24px;
  }

  .auth-hero h1 {
    font-size: 30px;
  }

  .auth-panel {
    padding: 32px 24px;
  }
}
</style>
