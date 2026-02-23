/**
 * 对话状态管理 Store
 * 管理多会话列表、当前会话消息、发送状态
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { nanoid } from 'nanoid'
import type { ChatMessage, ConversationSession } from '@/types/chat'

export const useChatStore = defineStore('chat', () => {
  // ====== 状态定义 ======

  /** 当前活跃会话 ID */
  const currentConversationId = ref<string>('')

  /** 历史会话列表（侧边栏展示） */
  const sessions = ref<ConversationSession[]>([])

  /** 当前会话的消息列表 */
  const messages = ref<ChatMessage[]>([])

  /** 是否正在发送中（禁用输入框） */
  const isSending = ref<boolean>(false)

  /** 是否使用流式模式 */
  const useStreamMode = ref<boolean>(true)

  /** 当前使用的模型名称 */
  const currentModel = ref<string>('')

  // ====== 计算属性 ======

  /** 是否有消息（用于显示空状态） */
  const hasMessages = computed(() => messages.value.length > 0)

  /** 当前会话标题 */
  const currentTitle = computed(() => {
    const session = sessions.value.find(s => s.id === currentConversationId.value)
    return session?.title || '新对话'
  })

  // ====== 方法 ======

  /**
   * 新建一个对话会话
   * 生成唯一 ID，并切换到新会话
   */
  function createNewSession(): string {
    const id = `conv_${nanoid(8)}`
    const session: ConversationSession = {
      id,
      title: '新对话',
      lastMessage: '',
      updatedAt: Date.now(),
      messageCount: 0,
    }
    sessions.value.unshift(session)  // 新会话排在最前面
    switchSession(id)
    console.log('[ChatStore] 创建新会话，ID:', id)
    return id
  }

  /**
   * 切换到指定会话，加载该会话的消息
   */
  function switchSession(sessionId: string): void {
    currentConversationId.value = sessionId
    // NOTE: 由于消息保存在前端内存，切换会话时清空消息列表
    // 实际生产中可以缓存每个会话的消息列表
    messages.value = []
    console.log('[ChatStore] 切换会话，ID:', sessionId)
  }

  /**
   * 添加用户消息到列表
   */
  function addUserMessage(content: string): ChatMessage {
    const message: ChatMessage = {
      id: nanoid(),
      role: 'user',
      content,
      timestamp: Date.now(),
    }
    messages.value.push(message)
    updateSession(content)
    console.log('[ChatStore] 添加用户消息:', content.substring(0, 50))
    return message
  }

  /**
   * 添加 AI 占位消息（流式输出时先占位，再逐步填充）
   */
  function addAssistantPlaceholder(): ChatMessage {
    const message: ChatMessage = {
      id: nanoid(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      isLoading: true,
    }
    messages.value.push(message)
    console.log('[ChatStore] 添加 AI 占位消息，ID:', message.id)
    return message
  }

  /**
   * 更新指定消息的内容（流式追加）
   */
  function appendToMessage(messageId: string, chunk: string): void {
    const msg = messages.value.find(m => m.id === messageId)
    if (msg) {
      msg.content += chunk
    }
  }

  /**
   * 将占位消息标记为完成（关闭 loading 状态）
   */
  function finalizeMessage(messageId: string): void {
    const msg = messages.value.find(m => m.id === messageId)
    if (msg) {
      msg.isLoading = false
      console.log('[ChatStore] 消息完成，ID:', messageId)
    }
  }

  /**
   * 标记消息为错误状态
   */
  function markMessageError(messageId: string, errorText: string): void {
    const msg = messages.value.find(m => m.id === messageId)
    if (msg) {
      msg.content = errorText
      msg.isLoading = false
      msg.isError = true
    }
  }

  /**
   * 更新当前会话的摘要信息
   */
  function updateSession(lastMessage: string): void {
    const session = sessions.value.find(s => s.id === currentConversationId.value)
    if (session) {
      session.lastMessage = lastMessage.substring(0, 50)
      session.updatedAt = Date.now()
      session.messageCount = messages.value.length
      // 用第一条消息作为标题
      if (session.title === '新对话' && lastMessage) {
        session.title = lastMessage.substring(0, 20) + (lastMessage.length > 20 ? '...' : '')
      }
    }
  }

  /**
   * 清空当前会话的所有消息
   */
  function clearCurrentMessages(): void {
    messages.value = []
    const session = sessions.value.find(s => s.id === currentConversationId.value)
    if (session) {
      session.messageCount = 0
      session.lastMessage = ''
    }
    console.log('[ChatStore] 已清空当前会话消息')
  }

  /**
   * 初始化：如果没有会话，自动创建一个
   */
  function init(): void {
    if (sessions.value.length === 0) {
      createNewSession()
    } else {
      // 恢复到最后一个会话
      currentConversationId.value = sessions.value[0].id
    }
  }

  return {
    // 状态
    currentConversationId,
    sessions,
    messages,
    isSending,
    useStreamMode,
    currentModel,
    // 计算属性
    hasMessages,
    currentTitle,
    // 方法
    init,
    createNewSession,
    switchSession,
    addUserMessage,
    addAssistantPlaceholder,
    appendToMessage,
    finalizeMessage,
    markMessageError,
    clearCurrentMessages,
  }
})
