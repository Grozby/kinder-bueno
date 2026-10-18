import { createRouter, createWebHistory } from 'vue-router'
import BoardView from '../views/BoardView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'board',
      component: BoardView,
      meta: { title: 'Pipeline' },
    },
    {
      path: '/sources',
      name: 'sources',
      component: () => import('../views/SourcesView.vue'),
      meta: { title: 'Sources' },
    },
  ],
})

// Each page names itself in the browser tab (WCAG 2.4.2)
router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · Bern Fit` : 'Bern Fit'
})

export default router
