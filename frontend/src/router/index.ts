import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
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
      meta: { shell: 'dashboard' },
    },
    { path: '/:pathMatch(.*)*', redirect: '/', meta: { shell: 'app' } },
  ],
})

export default router
