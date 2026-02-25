/**
 * 工作流模块路由配置
 */
import type { RouteRecordRaw } from 'vue-router'

const workflowsRoutes: RouteRecordRaw[] = [
  {
    path: '/workflows',
    name: 'Workflows',
    component: () => import('@/views/workflows/WorkflowsView.vue'),
    meta: {
      title: '工作流',
      icon: 'Connection',
    },
  },
]

export default workflowsRoutes
