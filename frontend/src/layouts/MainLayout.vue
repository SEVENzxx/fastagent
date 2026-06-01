<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/useAuthStore'
import { usePermissionStore } from '@/stores/usePermissionStore'

const router = useRouter()
const authStore = useAuthStore()
const permStore = usePermissionStore()

const username = computed(() => authStore.user?.displayName || authStore.user?.email || '已登录用户')
const isSuperuser = computed(() => authStore.user?.isSuperuser ?? false)
const homePath = computed(() => isSuperuser.value ? '/platform-admin' : '/')
const userInitial = computed(() => username.value.slice(0, 1).toUpperCase())

function handleUserCommand(command: string) {
  if (command === 'profile') {
    router.push('/profile')
    return
  }
  if (command === 'password') {
    router.push('/profile/password')
    return
  }
  if (command === 'logout') {
    authStore.logout()
  }
}

onMounted(async () => {
  if (authStore.isAuthenticated && !authStore.user) {
    try {
      await authStore.fetchUser()
    } catch {
      authStore.logout()
    }
  }
})
</script>

<template>
  <div class="main-layout">
    <aside class="sidebar">
      <button class="brand" type="button" @click="router.push(homePath)">
        <span class="brand-mark">FA</span>
        <span class="brand-text">FastAgent</span>
      </button>

      <el-menu :default-active="router.currentRoute.value.path" router class="sidebar-menu">
        <el-sub-menu v-if="isSuperuser" index="platform-admin">
          <template #title>
            <span class="nav-icon nav-icon-platform" />
            <span>平台管理</span>
          </template>
          <el-menu-item index="/platform-admin">平台总览</el-menu-item>
          <el-menu-item index="/platform-admin/tenants">租户管理</el-menu-item>
          <el-menu-item index="/platform-admin/plans">套餐管理</el-menu-item>
          <el-menu-item index="/platform-admin/llm-configs">LLM 模型池</el-menu-item>
          <el-menu-item index="/platform-admin/business">跨租户业务</el-menu-item>
          <el-menu-item index="/platform-admin/operations">审计与登录历史</el-menu-item>
          <el-menu-item index="/platform-admin/system">系统运维</el-menu-item>
        </el-sub-menu>

        <template v-if="!isSuperuser">
          <el-menu-item index="/">
            <span class="nav-icon nav-icon-workbench" />
            <span>会话工作台</span>
          </el-menu-item>

          <el-sub-menu index="business">
            <template #title>
              <span class="nav-icon nav-icon-contact" />
              <span>客户经营</span>
            </template>
            <el-menu-item index="/contacts">联系人管理</el-menu-item>
            <el-menu-item index="/products">商品管理</el-menu-item>
            <el-menu-item v-if="permStore.hasPermission('manage_products')" index="/products/categories">分类管理</el-menu-item>
            <el-menu-item index="/orders">订单管理</el-menu-item>
          </el-sub-menu>

          <el-sub-menu index="content-ai">
            <template #title>
              <span class="nav-icon nav-icon-kb" />
              <span>内容与 AI</span>
            </template>
            <el-menu-item index="/knowledge">知识文档</el-menu-item>
            <el-menu-item index="/qa-pairs">问答对</el-menu-item>
            <el-menu-item index="/marketing">营销资料</el-menu-item>
            <el-menu-item index="/images">图片库</el-menu-item>
            <el-menu-item index="/hit-testing">命中测试</el-menu-item>
          </el-sub-menu>

          <el-sub-menu index="analytics">
            <template #title>
              <span class="nav-icon nav-icon-platform" />
              <span>数据分析</span>
            </template>
            <el-menu-item index="/analytics">数据仪表盘</el-menu-item>
            <el-menu-item index="/analytics/usage">用量分析</el-menu-item>
          </el-sub-menu>

          <el-sub-menu index="organization-settings">
            <template #title>
              <span class="nav-icon nav-icon-team" />
              <span>组织与设置</span>
            </template>
            <el-menu-item v-if="permStore.hasPermission('manage_roles')" index="/admin/roles">角色管理</el-menu-item>
            <el-menu-item v-if="permStore.hasPermission('manage_employees')" index="/admin/employees">员工管理</el-menu-item>
            <el-menu-item index="/settings/wechat">企微设置</el-menu-item>
            <el-menu-item v-if="permStore.hasPermission('manage_sensitive_words')" index="/settings/sensitive-words">敏感词管理</el-menu-item>
          </el-sub-menu>

          <el-sub-menu index="tools">
            <template #title>
              <span class="nav-icon nav-icon-tool" />
              <span>常用工具</span>
            </template>
            <el-menu-item index="/tools/batch-add-wechat">批量加微信</el-menu-item>
            <el-menu-item index="/tools/account-binding">账号绑定</el-menu-item>
          </el-sub-menu>

          <el-menu-item index="/notifications">
            <span class="nav-icon nav-icon-qa" />
            <span>系统通知</span>
          </el-menu-item>
        </template>
      </el-menu>
    </aside>

    <section class="workspace">
      <header class="topbar">
        <div>
          <p class="topbar-label">管理后台</p>
          <h1>FastAgent 控制台</h1>
        </div>
        <div class="user-actions">
          <el-tag v-if="isSuperuser" type="danger" effect="light">超级管理员</el-tag>
          <el-dropdown trigger="click" @command="handleUserCommand">
            <button class="user-menu" type="button">
              <el-avatar :size="30">{{ userInitial }}</el-avatar>
              <span class="username">{{ username }}</span>
              <span class="chevron">⌄</span>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile">个人资料</el-dropdown-item>
                <el-dropdown-item command="password">修改密码</el-dropdown-item>
                <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="main-content">
        <router-view />
      </main>
    </section>
  </div>
</template>

<style scoped>
.main-layout {
  min-height: 100vh;
  display: flex;
  background: var(--app-bg);
}

.sidebar {
  width: 240px;
  min-width: 240px;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
}

.brand {
  height: 72px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
  border: 0;
  border-bottom: 1px solid var(--border);
  background: transparent;
  cursor: pointer;
  color: var(--text-strong);
}

.brand-mark {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: var(--primary);
  color: #fff;
  font-size: 13px;
  font-weight: 700;
}

.brand-text {
  font-size: 17px;
  font-weight: 700;
}

.sidebar-menu {
  flex: 1;
  border-right: 0;
  padding: 12px;
}

.sidebar-menu :deep(.el-menu-item),
.sidebar-menu :deep(.el-sub-menu__title) {
  height: 42px;
  margin-bottom: 4px;
  border-radius: 8px;
  color: var(--text);
}

.sidebar-menu :deep(.el-menu-item.is-active) {
  background: var(--primary-soft);
  color: var(--primary);
  font-weight: 600;
}

.nav-icon {
  width: 20px;
  height: 20px;
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-right: 8px;
  flex: 0 0 20px;
  color: currentColor;
}

.nav-icon::before,
.nav-icon::after {
  content: '';
  position: absolute;
  box-sizing: border-box;
}

.nav-icon-workbench::before {
  width: 15px;
  height: 12px;
  border: 1.6px solid currentColor;
  border-radius: 3px;
}

.nav-icon-workbench::after {
  width: 7px;
  height: 1.6px;
  left: 6px;
  top: 9px;
  background: currentColor;
  box-shadow: 0 -4px 0 currentColor;
}

.nav-icon-platform::before {
  width: 15px;
  height: 15px;
  border: 1.6px solid currentColor;
  border-radius: 3px;
}

.nav-icon-platform::after {
  width: 7px;
  height: 7px;
  border: 1.6px solid currentColor;
  border-radius: 999px;
}

.nav-icon-role::before {
  width: 14px;
  height: 14px;
  border: 1.6px solid currentColor;
  border-radius: 999px;
}

.nav-icon-role::after {
  width: 5px;
  height: 5px;
  border: 1.6px solid currentColor;
  border-radius: 999px;
  background: var(--surface);
}

.nav-icon-team::before,
.nav-icon-team::after {
  border: 1.6px solid currentColor;
  border-radius: 999px;
}

.nav-icon-team::before {
  top: 3px;
  left: 7px;
  width: 6px;
  height: 6px;
}

.nav-icon-team::after {
  left: 4px;
  bottom: 3px;
  width: 12px;
  height: 7px;
  border-top-left-radius: 7px;
  border-top-right-radius: 7px;
}

.nav-icon-folder::before {
  width: 14px;
  height: 12px;
  border: 1.6px solid currentColor;
  border-radius: 3px;
}

.nav-icon-folder::after {
  width: 7px;
  height: 4px;
  left: 4px;
  top: 4px;
  border-top: 1.6px solid currentColor;
  border-left: 1.6px solid currentColor;
  border-top-left-radius: 2px;
}

.nav-icon-contact::before,
.nav-icon-contact::after {
  border: 1.6px solid currentColor;
}

.nav-icon-contact::before {
  top: 3px;
  left: 7px;
  width: 6px;
  height: 6px;
  border-radius: 999px;
}

.nav-icon-contact::after {
  left: 4px;
  bottom: 3px;
  width: 12px;
  height: 8px;
  border-radius: 7px 7px 3px 3px;
}

.nav-icon-product::before {
  width: 14px;
  height: 12px;
  border: 1.6px solid currentColor;
  border-radius: 3px;
  transform: translateY(1px);
}

.nav-icon-product::after {
  width: 7px;
  height: 5px;
  top: 3px;
  border: 1.6px solid currentColor;
  border-bottom: 0;
  border-radius: 4px 4px 0 0;
}

.nav-icon-channel::before {
  width: 15px;
  height: 11px;
  border: 1.6px solid currentColor;
  border-radius: 4px;
}

.nav-icon-channel::after {
  width: 6px;
  height: 6px;
  right: 1px;
  bottom: 2px;
  border-right: 1.6px solid currentColor;
  border-bottom: 1.6px solid currentColor;
  transform: rotate(45deg);
}

.nav-icon-tool::before {
  width: 14px;
  height: 14px;
  border: 1.6px solid currentColor;
  border-radius: 4px;
}

.nav-icon-tool::after {
  width: 8px;
  height: 1.6px;
  background: currentColor;
  box-shadow: 0 -4px 0 currentColor, 0 4px 0 currentColor;
}

.nav-icon-link::before,
.nav-icon-link::after {
  width: 10px;
  height: 7px;
  border: 1.6px solid currentColor;
  border-radius: 999px;
}

.nav-icon-link::before {
  left: 2px;
  transform: rotate(-32deg);
}

.nav-icon-link::after {
  right: 2px;
  transform: rotate(-32deg);
}

.nav-icon-order::before {
  width: 13px;
  height: 14px;
  border: 1.6px solid currentColor;
  border-radius: 2px;
}

.nav-icon-order::after {
  width: 6px;
  height: 5px;
  top: 4px;
  left: 4px;
  border-bottom: 1.6px solid currentColor;
  border-right: 1.6px solid currentColor;
  transform: rotate(45deg);
}

.nav-icon-kb::before {
  width: 14px;
  height: 14px;
  border: 1.6px solid currentColor;
  border-radius: 2px;
}

.nav-icon-kb::after {
  width: 6px;
  height: 1.6px;
  left: 5px;
  top: 6px;
  background: currentColor;
  box-shadow: 0 4px 0 currentColor;
}

.nav-icon-qa::before {
  width: 12px;
  height: 10px;
  border: 1.6px solid currentColor;
  border-radius: 999px;
  transform: translateY(2px);
}

.nav-icon-qa::after {
  width: 5px;
  height: 5px;
  left: 5px;
  bottom: 3px;
  border-right: 1.6px solid currentColor;
  border-bottom: 1.6px solid currentColor;
  transform: rotate(45deg);
}

.nav-icon-test::before {
  width: 14px;
  height: 14px;
  border: 1.6px solid currentColor;
  border-radius: 999px;
}

.nav-icon-test::after {
  width: 5px;
  height: 5px;
  left: 6px;
  top: 4px;
  border: 1.6px solid currentColor;
  border-left: 0;
  border-top: 0;
  border-radius: 0 0 2px 0;
  transform: rotate(15deg);
}

.nav-icon-mkt::before {
  width: 13px;
  height: 14px;
  border: 1.6px solid currentColor;
  border-radius: 2px;
}

.nav-icon-mkt::after {
  width: 7px;
  height: 4px;
  left: 5px;
  top: 4px;
  border-top: 1.6px solid currentColor;
  border-radius: 2px 2px 0 0;
}

.nav-icon-img::before {
  width: 14px;
  height: 12px;
  border: 1.6px solid currentColor;
  border-radius: 3px;
}

.nav-icon-img::after {
  width: 5px;
  height: 5px;
  right: 3px;
  top: 3px;
  border: 1.6px solid currentColor;
  border-radius: 999px;
}

.workspace {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.topbar {
  min-height: 72px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 16px 28px;
  background: rgba(255, 255, 255, 0.88);
  border-bottom: 1px solid var(--border);
  backdrop-filter: blur(16px);
}

.topbar-label {
  color: var(--text-muted);
  font-size: 12px;
}

.topbar h1 {
  margin-top: 2px;
  color: var(--text-strong);
  font-size: 20px;
  font-weight: 700;
}

.user-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  min-width: 0;
}

.username {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-strong);
  font-weight: 500;
}

.user-menu {
  height: 38px;
  display: inline-flex;
  align-items: center;
  gap: 9px;
  padding: 3px 8px 3px 4px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--text-strong);
  cursor: pointer;
}

.user-menu:hover,
.user-menu:focus-visible {
  border-color: var(--border);
  background: var(--surface-soft);
  outline: none;
}

.chevron {
  color: var(--text-muted);
  font-size: 13px;
  line-height: 1;
}

.main-content {
  flex: 1;
  padding: 28px;
  overflow: auto;
}

@media (max-width: 860px) {
  .main-layout {
    flex-direction: column;
  }

  .sidebar {
    width: 100%;
    min-width: 0;
  }

  .brand {
    height: 60px;
  }

  .sidebar-menu {
    display: flex;
    overflow-x: auto;
    padding: 8px 12px;
  }

  .topbar {
    align-items: flex-start;
    flex-direction: column;
    padding: 16px 20px;
  }

  .user-actions {
    width: 100%;
    justify-content: flex-start;
    flex-wrap: wrap;
  }

  .main-content {
    padding: 20px;
  }
}
</style>
