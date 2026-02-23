<template>
  <!--
    主布局组件：侧边栏 + 头部 + 内容区
    结构：左侧固定侧边栏 + 右侧主区域（顶部Header + 内容RouterView）
  -->
  <div class="main-layout" :class="{ 'sidebar-collapsed': appStore.sidebarCollapsed }">
    <!-- ===== 左侧导航侧边栏 ===== -->
    <aside class="sidebar">
      <!-- 品牌 Logo 区域 -->
      <div class="sidebar-brand">
        <div class="brand-logo">
          <svg viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect width="32" height="32" rx="8" fill="url(#logo-gradient)" />
            <path d="M8 22L12 10L16 18L20 10L24 22" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
            <defs>
              <linearGradient id="logo-gradient" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
                <stop stop-color="#7c3aed"/>
                <stop offset="1" stop-color="#06b6d4"/>
              </linearGradient>
            </defs>
          </svg>
        </div>
        <div class="brand-text" v-show="!appStore.sidebarCollapsed">
          <span class="brand-name">AI Agent</span>
          <span class="brand-sub">智能体平台</span>
        </div>
      </div>

      <!-- 导航菜单 -->
      <nav class="sidebar-nav">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
        >
          <el-icon class="nav-icon" :size="20">
            <component :is="item.icon" />
          </el-icon>
          <span class="nav-label" v-show="!appStore.sidebarCollapsed">{{ item.label }}</span>
          <!-- 新对话按钮（仅 Chat 项显示） -->
          <button
            v-if="item.path === '/chat' && !appStore.sidebarCollapsed"
            class="new-chat-btn"
            @click.prevent="handleNewChat"
            title="新建对话"
          >
            <el-icon :size="14"><Plus /></el-icon>
          </button>
        </router-link>
      </nav>

      <!-- 侧边栏底部：系统信息 -->
      <div class="sidebar-footer" v-show="!appStore.sidebarCollapsed">
        <div class="system-status">
          <span class="status-dot"></span>
          <span class="status-text">后端服务运行中</span>
        </div>
        <div class="api-endpoint">localhost:8002</div>
      </div>
    </aside>

    <!-- ===== 右侧主区域 ===== -->
    <div class="main-area">
      <!-- 顶部 Header -->
      <header class="main-header">
        <!-- 折叠侧边栏按钮 -->
        <button class="collapse-btn" @click="appStore.toggleSidebar" title="折叠侧边栏">
          <el-icon :size="18"><Expand v-if="appStore.sidebarCollapsed" /><Fold v-else /></el-icon>
        </button>

        <!-- 当前页面标题 -->
        <div class="header-title">
          <span class="page-title">{{ currentPageTitle }}</span>
        </div>

        <!-- 右侧操作区 -->
        <div class="header-actions">
          <span class="version-badge">v1.0</span>
        </div>
      </header>

      <!-- 内容区：路由视图 -->
      <main class="main-content">
        <router-view v-slot="{ Component }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ChatDotSquare, Setting, MagicStick, Connection,
  Plus, Expand, Fold, DataLine
} from '@element-plus/icons-vue'
import { useAppStore } from '@/stores/app'
import { useChatStore } from '@/stores/chat'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const chatStore = useChatStore()

// 导航菜单配置
const navItems = [
  { path: '/dashboard', label: '仪表盘', icon: DataLine },
  { path: '/chat', label: 'AI 对话', icon: ChatDotSquare },
  { path: '/agents', label: 'Agent 执行', icon: Setting },
  { path: '/skills', label: '技能库', icon: MagicStick },
  { path: '/workflows', label: '工作流', icon: Connection },
]

/**
 * 判断导航项是否激活（兼容子路由匹配）
 */
function isActive(path: string): boolean {
  return route.path.startsWith(path)
}

/**
 * 获取当前页面标题，用于 Header 显示
 */
const currentPageTitle = computed(() => {
  const title = route.meta?.title as string | undefined
  return title || 'AI Agent 平台'
})

/**
 * 新建对话处理：创建新会话并跳转到 Chat 页面
 */
function handleNewChat(): void {
  chatStore.createNewSession()
  router.push('/chat')
  console.log('[Layout] 创建新对话会话')
}
</script>

<style scoped>
/* ====================================================
 * 布局整体结构
 * ==================================================== */
.main-layout {
  display: flex;
  height: 100vh;
  background: var(--color-bg-secondary);
  overflow: hidden;
}

/* ====================================================
 * 侧边栏样式
 * ==================================================== */
.sidebar {
  width: var(--sidebar-width);
  min-width: var(--sidebar-width);
  height: 100vh;
  background: var(--color-bg-primary);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  transition: width var(--transition-normal), min-width var(--transition-normal);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
  z-index: 10;
}

/* 折叠状态的侧边栏 */
.main-layout.sidebar-collapsed .sidebar {
  width: 64px;
  min-width: 64px;
}

/* --- 品牌区域 --- */
.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 16px;
  border-bottom: 1px solid var(--color-border-light);
}

.brand-logo svg {
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  border-radius: 8px;
}

.brand-text {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.brand-name {
  font-family: var(--font-heading);
  font-size: 1rem;
  font-weight: 700;
  color: var(--color-text-primary);
  white-space: nowrap;
}

.brand-sub {
  font-size: 0.7rem;
  color: var(--color-text-muted);
  white-space: nowrap;
}

/* --- 导航菜单 --- */
.sidebar-nav {
  flex: 1;
  padding: 12px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  cursor: pointer;
  text-decoration: none;
  color: var(--color-text-secondary);
  font-size: 0.875rem;
  font-weight: 500;
  transition: all var(--transition-fast);
  position: relative;
  white-space: nowrap;
  overflow: hidden;
}

.nav-item:hover {
  background: var(--color-bg-hover);
  color: var(--color-primary);
}

.nav-item.active {
  background: var(--color-primary-lighter);
  color: var(--color-primary);
}

.nav-icon {
  flex-shrink: 0;
  color: inherit;
}

.nav-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 新建对话按钮 */
.new-chat-btn {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--transition-fast);
  opacity: 0;
}

.nav-item:hover .new-chat-btn {
  opacity: 1;
}

.new-chat-btn:hover {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: white;
}

/* --- 侧边栏底部 --- */
.sidebar-footer {
  padding: 16px;
  border-top: 1px solid var(--color-border-light);
}

.system-status {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-success);
  /* 闪烁动画表示运行中 */
  animation: pulse-dot 2s ease infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.status-text {
  font-size: 0.75rem;
  color: var(--color-success);
  font-weight: 500;
}

.api-endpoint {
  font-size: 0.7rem;
  color: var(--color-text-muted);
  font-family: var(--font-mono);
}

/* ====================================================
 * 右侧主区域
 * ==================================================== */
.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* --- 顶部 Header --- */
.main-header {
  height: var(--header-height);
  min-height: var(--header-height);
  background: var(--color-bg-primary);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
  box-shadow: var(--shadow-sm);
}

.collapse-btn {
  width: 36px;
  height: 36px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

.collapse-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-primary);
  border-color: var(--color-primary);
}

.header-title {
  flex: 1;
}

.page-title {
  font-family: var(--font-heading);
  font-size: 1rem;
  font-weight: 600;
  color: var(--color-text-primary);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.version-badge {
  font-size: 0.7rem;
  padding: 2px 8px;
  background: var(--color-primary-lighter);
  color: var(--color-primary);
  border-radius: var(--radius-full);
  font-weight: 600;
  border: 1px solid #ddd6fe;
}

/* --- 内容区域 --- */
.main-content {
  flex: 1;
  overflow: hidden;
  position: relative;
}

/* 路由切换动画 */
.page-fade-enter-active,
.page-fade-leave-active {
  transition: opacity var(--transition-fast), transform var(--transition-fast);
}

.page-fade-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.page-fade-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
