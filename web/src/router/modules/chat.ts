/**
 * 对话模块路由配置
 * AI 对话功能（普通模式 + 流式模式）
 */
import type { RouteRecordRaw } from 'vue-router'

const chatRoutes: RouteRecordRaw[] = [
  {
    path: '/chat',
    name: 'Chat',
    component: () => import('@/views/chat/ChatView.vue'),
    meta: {
      title: 'AI 对话',
      icon: 'ChatDotSquare',
    },
  },
]

export default chatRoutes
