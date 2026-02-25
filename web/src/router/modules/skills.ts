/**
 * 技能库模块路由配置
 */
import type { RouteRecordRaw } from 'vue-router'

const skillsRoutes: RouteRecordRaw[] = [
  {
    path: '/skills',
    name: 'Skills',
    component: () => import('@/views/skills/SkillsView.vue'),
    meta: {
      title: '技能库',
      icon: 'MagicStick',
    },
  },
]

export default skillsRoutes
