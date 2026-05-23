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
      path: '/register',
      name: 'register',
      meta: { public: true },
      component: () => import('../views/auth/RegisterView.vue'),
    },
  ],
})

router.beforeEach((to) => {
  const authStore = useAuthStore()
  const isPublicRoute = to.meta.public === true

  if (!authStore.isAuthenticated && !isPublicRoute) {
    return {
      path: '/login',
      query: { redirect: to.fullPath },
    }
  }

  if (authStore.isAuthenticated && isPublicRoute) {
    return { path: '/' }
  }
})

export default router
