import { createRouter, createWebHistory } from 'vue-router'
import { t } from '@/i18n'
import { refreshSession } from '@/session'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  scrollBehavior(to, _from, savedPosition) {
    if (savedPosition) return savedPosition
    if (to.hash) return { el: to.hash, top: 88 }
    return { top: 0 }
  },
  routes: [
    {
      path: '/',
      name: 'introduction',
      component: () => import('@/views/IntroductionView.vue'),
      meta: { title: '平台介绍', hidden: true, layout: 'cover' },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { title: '登录', hidden: true, layout: 'cover' },
    },
    {
      path: '/legacy',
      name: 'legacy',
      component: () => import('@/views/LegacyView.vue'),
      meta: {
        title: 'Benchmark',
        icon: 'Histogram',
        children: [
          { path: '/legacy?view=/', title: '仪表盘', icon: 'Odometer' },
          { path: '/legacy?view=/problems', title: '题目', icon: 'Document' },
          { path: '/legacy?view=/submissions', title: '提交记录', icon: 'List' },
          { path: '/legacy?view=/model-stats', title: '模型统计', icon: 'DataAnalysis' },
        ],
      },
    },
    {
      path: '/lab',
      name: 'lab',
      component: () => import('@/views/LabView.vue'),
      meta: { title: '生成与质量评测', icon: 'Experiment' },
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('@/views/DashboardView.vue'),
      meta: { title: '总览', icon: 'Odometer' },
    },
    {
      path: '/agreement',
      name: 'agreement',
      component: () => import('@/views/AgreementView.vue'),
      meta: { title: '一致性分析', icon: 'ScaleToOriginal' },
    },
    {
      path: '/slots',
      name: 'slots',
      component: () => import('@/views/SlotsView.vue'),
      meta: { title: '对拍槽位', icon: 'List' },
    },
    {
      path: '/problems',
      name: 'problems',
      component: () => import('@/views/ProblemsView.vue'),
      meta: { title: '题目与语料', icon: 'Document', hidden: true },
    },
    {
      path: '/fixes',
      name: 'fixes',
      component: () => import('@/views/FixesView.vue'),
      meta: { title: '语料修复', icon: 'Tools', hidden: true },
    },
    {
      path: '/models',
      name: 'models',
      component: () => import('@/views/ModelStatsView.vue'),
      meta: { title: '模型', icon: 'DataAnalysis', hidden: true },
    },
    {
      path: '/problems/:qid',
      name: 'detail',
      component: () => import('@/views/DetailView.vue'),
      meta: { title: '题目详情', hidden: true },
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/',
      meta: { hidden: true },
    },
  ],
})

router.beforeEach(async (to) => {
  const title = (to.meta.title as string) || '多语言代码质量评测'
  document.title = `${t(title)} - MCIBench`
  if (to.meta.layout === 'cover') return true   // public introduction and the login page
  const state = await refreshSession()
  if (state === 'denied') return { path: '/login', query: { next: to.fullPath } }
  return true
})

export default router
