<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/useAuthStore'
import { usePermissionStore } from '@/stores/usePermissionStore'

const router = useRouter()
const authStore = useAuthStore()
const permStore = usePermissionStore()

const username = computed(() => authStore.user?.displayName || authStore.user?.email || '用户')
const isSuperuser = computed(() => authStore.user?.isSuperuser ?? false)

const quickLinks = computed(() => {
  const links: { title: string; description: string; path: string; show: boolean }[] = [
    {
      title: '角色管理',
      description: '维护角色信息并分配权限',
      path: '/admin/roles',
      show: permStore.hasPermission('manage_roles') || isSuperuser.value,
    },
  ]
  return links.filter((link) => link.show)
})
</script>

<template>
  <div class="home">
    <section class="overview">
      <div>
        <p class="eyebrow">欢迎回来</p>
        <h2>{{ username }}</h2>
        <p class="summary">这里汇总了当前账号的基础状态和常用入口。</p>
      </div>
      <el-tag v-if="isSuperuser" type="danger" effect="light">超级管理员</el-tag>
    </section>

    <section class="stats-grid">
      <article class="stat-card">
        <span class="stat-label">可用入口</span>
        <strong>{{ quickLinks.length }}</strong>
        <p>当前账号可访问功能</p>
      </article>
      <article class="stat-card">
        <span class="stat-label">账号状态</span>
        <strong>正常</strong>
        <p>已通过登录校验</p>
      </article>
      <article class="stat-card">
        <span class="stat-label">身份</span>
        <strong>{{ isSuperuser ? '超级管理员' : '普通用户' }}</strong>
        <p>按角色显示可访问菜单</p>
      </article>
    </section>

    <section class="panel">
      <div class="panel-header">
        <div>
          <h3>快捷入口</h3>
          <p>常用管理功能</p>
        </div>
      </div>

      <div v-if="quickLinks.length" class="quick-links">
        <button
          v-for="link in quickLinks"
          :key="link.path"
          class="quick-link"
          type="button"
          @click="router.push(link.path)"
        >
          <span>{{ link.title }}</span>
          <small>{{ link.description }}</small>
        </button>
      </div>
      <el-empty v-else description="暂无可用入口" />
    </section>
  </div>
</template>

<style scoped>
.home {
  display: grid;
  gap: 20px;
}

.overview,
.panel,
.stat-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.overview {
  min-height: 150px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 28px;
}

.eyebrow,
.stat-label {
  color: var(--text-muted);
  font-size: 13px;
  font-weight: 600;
}

.overview h2 {
  margin-top: 8px;
  color: var(--text-strong);
  font-size: 28px;
  font-weight: 700;
}

.summary {
  margin-top: 10px;
  color: var(--text);
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.stat-card {
  padding: 20px;
}

.stat-card strong {
  display: block;
  margin-top: 10px;
  color: var(--text-strong);
  font-size: 26px;
}

.stat-card p {
  margin-top: 6px;
  color: var(--text-muted);
}

.panel {
  padding: 22px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.panel-header h3 {
  color: var(--text-strong);
  font-size: 18px;
}

.panel-header p {
  margin-top: 3px;
  color: var(--text-muted);
}

.quick-links {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.quick-link {
  display: grid;
  gap: 6px;
  min-height: 92px;
  padding: 18px;
  text-align: left;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-soft);
  cursor: pointer;
  transition:
    border-color 0.2s,
    box-shadow 0.2s,
    transform 0.2s;
}

.quick-link:hover {
  border-color: #bfdbfe;
  box-shadow: 0 10px 22px rgba(37, 99, 235, 0.08);
  transform: translateY(-1px);
}

.quick-link span {
  color: var(--text-strong);
  font-weight: 700;
}

.quick-link small {
  color: var(--text-muted);
}

@media (max-width: 760px) {
  .overview {
    flex-direction: column;
    padding: 22px;
  }

  .stats-grid {
    grid-template-columns: 1fr;
  }
}
</style>
