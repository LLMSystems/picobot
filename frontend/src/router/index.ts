import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'empty',
      component: () => import('@/views/EmptyView.vue'),
    },
    {
      path: '/c/:id',
      name: 'chat',
      component: () => import('@/views/ChatView.vue'),
      props: true,
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('@/views/DashboardView.vue'),
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

export default router
