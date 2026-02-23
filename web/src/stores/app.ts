/**
 * 全局应用状态 Store
 * 管理应用级别的全局状态（侧边栏折叠、加载状态等）
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAppStore = defineStore('app', () => {
  /** 侧边栏是否折叠 */
  const sidebarCollapsed = ref<boolean>(false)

  /** 全局页面加载状态 */
  const globalLoading = ref<boolean>(false)

  /** 全局加载文字提示 */
  const loadingText = ref<string>('加载中...')

  /**
   * 切换侧边栏折叠状态
   */
  function toggleSidebar(): void {
    sidebarCollapsed.value = !sidebarCollapsed.value
    console.log('[AppStore] 侧边栏状态:', sidebarCollapsed.value ? '折叠' : '展开')
  }

  /**
   * 显示全局加载状态
   */
  function showLoading(text = '加载中...'): void {
    loadingText.value = text
    globalLoading.value = true
  }

  /**
   * 隐藏全局加载状态
   */
  function hideLoading(): void {
    globalLoading.value = false
  }

  return {
    sidebarCollapsed,
    globalLoading,
    loadingText,
    toggleSidebar,
    showLoading,
    hideLoading,
  }
})
