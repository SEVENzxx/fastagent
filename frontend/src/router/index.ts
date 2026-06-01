import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/useAuthStore'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: () => import('../layouts/MainLayout.vue'),
      children: [
        {
          path: '',
          name: 'home',
          component: () => import('../views/workbench/WorkbenchView.vue'),
        },
        {
          path: 'admin/roles',
          name: 'admin-roles',
          component: () => import('../views/admin/RoleListPage.vue'),
        },
        {
          path: 'admin/employees',
          name: 'admin-employees',
          component: () => import('../views/admin/EmployeeListPage.vue'),
        },
        {
          path: 'admin/permissions',
          name: 'admin-permissions',
          component: () => import('../views/admin/PermissionListPage.vue'),
        },
        {
          path: 'platform-admin',
          name: 'platform-admin-dashboard',
          meta: { superuser: true },
          component: () => import('../views/platform/AdminDashboardView.vue'),
        },
        {
          path: 'platform-admin/tenants',
          name: 'platform-admin-tenants',
          meta: { superuser: true },
          component: () => import('../views/platform/AdminResourceView.vue'),
          props: { resource: 'tenants' },
        },
        {
          path: 'platform-admin/plans',
          name: 'platform-admin-plans',
          meta: { superuser: true },
          component: () => import('../views/platform/AdminResourceView.vue'),
          props: { resource: 'plans' },
        },
        {
          path: 'platform-admin/llm-configs',
          name: 'platform-admin-llm-configs',
          meta: { superuser: true },
          component: () => import('../views/platform/AdminResourceView.vue'),
          props: { resource: 'llm' },
        },
        {
          path: 'platform-admin/business',
          name: 'platform-admin-business',
          meta: { superuser: true },
          component: () => import('../views/platform/AdminBusinessView.vue'),
        },
        {
          path: 'platform-admin/operations',
          name: 'platform-admin-operations',
          meta: { superuser: true },
          component: () => import('../views/platform/AdminOperationsView.vue'),
        },
        {
          path: 'platform-admin/system',
          name: 'platform-admin-system',
          meta: { superuser: true },
          component: () => import('../views/platform/AdminSystemView.vue'),
        },
        {
          path: 'analytics',
          name: 'analytics',
          component: () => import('../views/analytics/TenantDashboardView.vue'),
        },
        {
          path: 'analytics/usage',
          name: 'analytics-usage',
          component: () => import('../views/analytics/UsageLogView.vue'),
        },
        {
          path: 'products',
          name: 'products',
          component: () => import('../views/products/ProductListView.vue'),
        },
        {
          path: 'products/categories',
          name: 'products-categories',
          component: () => import('../views/products/CategoryManagePage.vue'),
        },
        {
          path: 'contacts',
          name: 'contacts',
          component: () => import('../views/contacts/ContactListView.vue'),
        },
        {
          path: 'contacts/:id',
          name: 'contact-detail',
          component: () => import('../views/contacts/ContactDetailPage.vue'),
        },
        {
          path: 'orders',
          name: 'orders',
          component: () => import('../views/orders/OrderListView.vue'),
        },
        {
          path: 'knowledge',
          name: 'knowledge',
          component: () => import('../views/knowledge/KnowledgeDocList.vue'),
        },
        {
          path: 'knowledge/:id',
          name: 'knowledge-detail',
          component: () => import('../views/knowledge/KnowledgeDocDetail.vue'),
        },
        {
          path: 'qa-pairs',
          name: 'qa-pairs',
          component: () => import('../views/knowledge/QAPairList.vue'),
        },
        {
          path: 'marketing',
          name: 'marketing',
          component: () => import('../views/knowledge/MarketingDocList.vue'),
        },
        {
          path: 'images',
          name: 'images',
          component: () => import('../views/knowledge/ImageLibrary.vue'),
        },
        {
          path: 'hit-testing',
          name: 'hit-testing',
          component: () => import('../views/knowledge/HitTesting.vue'),
        },
        {
          path: 'settings/wechat',
          name: 'settings-wechat',
          component: () => import('../views/settings/WeChatSettings.vue'),
        },
        {
          path: 'settings/sensitive-words',
          name: 'settings-sensitive-words',
          component: () => import('../views/settings/SensitiveWordSettings.vue'),
        },
        {
          path: 'notifications',
          name: 'notifications',
          component: () => import('../views/NotificationsView.vue'),
        },
        {
          path: 'tools/batch-add-wechat',
          name: 'tools-batch-add-wechat',
          component: () => import('../views/tools/BatchAddWeChat.vue'),
        },
        {
          path: 'tools/account-binding',
          name: 'tools-account-binding',
          component: () => import('../views/tools/AccountBinding.vue'),
        },
        {
          path: 'profile',
          name: 'profile',
          component: () => import('../views/profile/ProfilePage.vue'),
        },
        {
          path: 'profile/password',
          name: 'profile-password',
          component: () => import('../views/profile/ChangePasswordPage.vue'),
        },
      ],
    },
    {
      path: '/login',
      name: 'login',
      meta: { public: true },
      component: () => import('../views/auth/LoginView.vue'),
    },
    {
      path: '/welcome',
      name: 'welcome',
      meta: { public: true },
      component: () => import('../views/LandingView.vue'),
    },
  ],
})

router.beforeEach(async (to) => {
  const authStore = useAuthStore()
  const isPublicRoute = to.meta.public === true

  if (!authStore.isAuthenticated && !isPublicRoute) {
    return { path: '/welcome', query: { redirect: to.fullPath } }
  }

  if (authStore.isAuthenticated && !authStore.user) {
    try {
      await authStore.fetchUser()
    } catch {
      authStore.clearAuth()
      return { path: '/welcome' }
    }
  }

  if (authStore.isAuthenticated && isPublicRoute) {
    return { path: authStore.user?.isSuperuser ? '/platform-admin' : '/' }
  }

  if (authStore.user?.isSuperuser) {
    const isPlatformRoute = to.path.startsWith('/platform-admin')
    const isPersonalRoute = to.path === '/profile' || to.path === '/profile/password'
    if (!isPlatformRoute && !isPersonalRoute) {
      return { path: '/platform-admin' }
    }
  } else if (to.meta.superuser === true) {
    return { path: '/' }
  }
})

export default router
