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
          <span class="username">{{ username }}</span>
          <el-button size="small" @click="authStore.logout()">退出</el-button>
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
  display: inline-flex;
  justify-content: center;
  margin-right: 8px;
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
