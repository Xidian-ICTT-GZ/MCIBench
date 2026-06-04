import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: () => import('@/views/DashboardView.vue'),
      meta: { title: 'Dashboard', icon: 'Odometer' },
    },
    {
      path: '/problems',
      name: 'problems',
      component: () => import('@/views/ProblemsView.vue'),
      meta: { title: 'Problems', icon: 'Document' },
    },
    {
      path: '/submissions',
      name: 'submissions',
      component: () => import('@/views/SubmissionsView.vue'),
      meta: { title: 'Submissions', icon: 'List' },
    },
    {
      path: '/model-stats',
      name: 'model-stats',
      component: () => import('@/views/ModelStatsView.vue'),
      meta: { title: 'Model Stats', icon: 'DataAnalysis' },
    },
    {
      path: '/problems/:qid',
      name: 'detail',
      component: () => import('@/views/DetailView.vue'),
      meta: { title: 'Detail', hidden: true },
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/',
      meta: { hidden: true },
    },
  ],
})

router.beforeEach((to) => {
  const title = (to.meta.title as string) || 'MCIBench'
  document.title = `${title} - MCIBench`
})

export default router
