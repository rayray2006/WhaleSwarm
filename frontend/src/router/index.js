import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: () => import('../views/Home.vue'),
  },
  {
    path: '/process/:projectId',
    name: 'MainView',
    component: () => import('../views/MainView.vue'),
  },
  {
    path: '/simulation/:simId',
    name: 'SimulationView',
    component: () => import('../views/SimulationView.vue'),
  },
  {
    path: '/simulation/:simId/start',
    name: 'SimulationRunView',
    component: () => import('../views/SimulationRunView.vue'),
  },
  {
    path: '/report/:reportId',
    name: 'ReportView',
    component: () => import('../views/ReportView.vue'),
  },
  {
    path: '/interaction/:reportId',
    name: 'InteractionView',
    component: () => import('../views/InteractionView.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
