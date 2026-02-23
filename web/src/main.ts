/**
 * 应用程序入口文件
 * 初始化 Vue 3 应用、注册全局插件（Element Plus、Pinia、Vue Router）
 */
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import 'element-plus/dist/index.css' // 引入完整的 Element Plus 样式


import App from './App.vue'
import router from './router'

// 全局样式（含 CSS 变量、Markdown 渲染样式、Element Plus 主题覆盖）
import './styles/global.css'

// 创建 Vue 应用实例
const app = createApp(App)

// 注册 Element Plus 图标组件（全局可用）
// NOTE: 图标命名规则：el-icon-[kebab-case] 对应 PascalCase 导出名
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

// 注册 Pinia（状态管理）
const pinia = createPinia()
app.use(pinia)

// 注册 Vue Router（路由）
app.use(router)

// 注册 Element Plus（UI 组件库），使用中文语言包
app.use(ElementPlus, {
  locale: zhCn,
  size: 'default',
})

console.log('[应用启动] AI Agent 前端工程初始化完成')

// 挂载应用
app.mount('#app')
