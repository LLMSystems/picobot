import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { shell: 'auth', public: true },
    },
    {
      path: '/register',
      name: 'register',
      component: () => import('@/views/RegisterView.vue'),
      meta: { shell: 'auth', public: true },
    },
    {
      path: '/',
      name: 'empty',
      component: () => import('@/views/EmptyView.vue'),
      meta: { shell: 'app' },
    },
    {
      path: '/c/:id',
      name: 'chat',
      component: () => import('@/views/ChatView.vue'),
      props: true,
      meta: { shell: 'app' },
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('@/views/DashboardView.vue'),
      meta: { shell: 'dashboard', requiresAdmin: true },
    },
    { path: '/:pathMatch(.*)*', redirect: '/', meta: { shell: 'app' } },
  ],
})

// Auth guard: probe the session once on first navigation, then keep
// unauthenticated users on the public auth pages and authenticated users off
// them.
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.ready) {
    await auth.fetchMe()
  }
  const isPublic = to.meta.public === true
  if (!auth.isAuthenticated && !isPublic) {
    return {
      name: 'login',
      query: to.fullPath !== '/' ? { redirect: to.fullPath } : undefined,
    }
  }
  if (auth.isAuthenticated && isPublic) {
    return { path: '/' }
  }
  // Admin-only routes (the operational dashboard) are off-limits to regular users.
  if (to.meta.requiresAdmin === true && !auth.isAdmin) {
    return { path: '/' }
  }
  return true
})

export default router
