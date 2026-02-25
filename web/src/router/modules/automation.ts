/**
 * Automation 自动化服务模块路由配置
 */
import type { RouteRecordRaw } from 'vue-router'

const automationRoutes: RouteRecordRaw[] = [
  {
    path: '/automation',
    name: 'Automation',
    component: () => import('@/views/automation/AutomationView.vue'),
    meta: {
      title: '自动化服务',
      icon: 'Tools',
    },
  },
]

export default automationRoutes
