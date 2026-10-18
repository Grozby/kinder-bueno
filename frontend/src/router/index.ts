import { createRouter, createWebHistory } from 'vue-router'
import BoardView from '../views/BoardView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'board',
      component: BoardView,
    },
    {
      path: '/sources',
      name: 'sources',
      component: () => import('../views/SourcesView.vue'),
    },
  ],
})

export default router
