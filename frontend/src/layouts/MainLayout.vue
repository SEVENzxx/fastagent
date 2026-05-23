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
      <button class="brand" type="button" @click="router.push('/')">
        <span class="brand-mark">FA</span>
        <span class="brand-text">FastAgent</span>
      </button>

      <el-menu :default-active="router.currentRoute.value.path" router class="sidebar-menu">
        <el-menu-item index="/">
          <span class="nav-icon">⌂</span>
          <span>工作台</span>
        </el-menu-item>

        <template v-if="permStore.hasPermission('manage_roles') || isSuperuser">
          <el-menu-item index="/admin/roles">
            <span class="nav-icon">⚙</span>
            <span>角色管理</span>
          </el-menu-item>
        </template>
        <template v-if="permStore.hasPermission('manage_employees') || isSuperuser">
          <el-menu-item index="/admin/employees">
            <span class="nav-icon nav-icon-team" />
            <span>员工管理</span>
          </el-menu-item>
        </template>
        <template v-if="permStore.hasPermission('manage_employees') || isSuperuser">
          <el-menu-item index="/products/categories">
            <span class="nav-icon nav-icon-folder" />
            <span>分类管理</span>
          </el-menu-item>
        </template>
        <el-menu-item index="/products">
          <span class="nav-icon">📦</span>
          <span>商品管理</span>
        </el-menu-item>
        <el-menu-item index="/contacts">
          <span class="nav-icon nav-icon-contact" />
          <span>联系人管理</span>
        </el-menu-item>
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
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-right: 8px;
}

.nav-icon-team {
  position: relative;
}

.nav-icon-team::before,
.nav-icon-team::after {
  content: '';
  position: absolute;
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

.nav-icon-folder {
  position: relative;
  width: 20px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-right: 8px;
}

.nav-icon-folder::before {
  content: '';
  width: 14px;
  height: 12px;
  border: 1.6px solid currentColor;
  border-radius: 3px;
}

.nav-icon-contact {
  position: relative;
}

.nav-icon-contact::before,
.nav-icon-contact::after {
  content: '';
  position: absolute;
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
