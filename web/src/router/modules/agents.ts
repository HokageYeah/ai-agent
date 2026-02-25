/**
 * Agent 执行模块路由配置
 */
import type { RouteRecordRaw } from 'vue-router'

const agentsRoutes: RouteRecordRaw[] = [
  {
    path: '/agents',
    name: 'Agents',
    component: () => import('@/views/agents/AgentsView.vue'),
    meta: {
      title: 'Agent 执行',
      icon: 'Setting',
    },
  },
]

export default agentsRoutes
