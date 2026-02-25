/**
 * 路由入口文件
 * 使用 import.meta.glob 动态加载 modules 目录下所有路由模块
 * 每个模块文件导出一个 RouteRecordRaw[] 数组（默认导出）
 */
import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

// 使用 Vite 的 glob 导入，eager: true 表示同步加载（避免异步问题）
const modules = import.meta.glob('./modules/**/*.ts', { eager: true })

// 收集所有模块的路由配置
const moduleRoutes: RouteRecordRaw[] = []

// 遍历所有模块文件，将其默认导出的路由数组合并
Object.keys(modules).forEach((key) => {
  const module = modules[key] as { default: RouteRecordRaw[] }
  if (module.default && Array.isArray(module.default)) {
    moduleRoutes.push(...module.default)
    console.log(`[路由] 已加载模块路由: ${key}，共 ${module.default.length} 条`)
  }
})

// 完整路由配置：根路由 + 模块路由 + 404 兜底
const routes: RouteRecordRaw[] = [
  {
    // 根路径重定向到仪表盘
    path: '/',
    redirect: '/dashboard',
  },
  {
    // 主布局路由（包含侧边栏、顶栏）
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/dashboard/DashboardView.vue'),
        meta: { title: '仪表盘', icon: 'Odometer' },
      },
      // 合并各模块路由到主布局下
      ...moduleRoutes,
    ],
  },
  {
    // 404 页面兜底
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    redirect: '/dashboard',
  },
]

// 创建路由器实例，使用 HTML5 History 模式
const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    // 路由跳转后滚动到顶部
    return { top: 0 }
  },
})

// 全局路由守卫：设置 document.title
router.afterEach((to) => {
  const title = to.meta?.title as string | undefined
  document.title = title ? `${title} - AI Agent 平台` : 'AI Agent 智能体平台'
  console.log(`[路由跳转] 进入: ${to.path}，标题: ${document.title}`)
})

export default router
