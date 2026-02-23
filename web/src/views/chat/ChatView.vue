<template>
  <div class="chat-view">
    <!-- ===== 左侧会话列表 ===== -->
    <div class="chat-sidebar">
      <div class="chat-sidebar-header">
        <span class="sidebar-label">对话列表</span>
        <el-button
          type="primary"
          size="small"
          circle
          :icon="Plus"
          title="新建对话"
          @click="chatStore.createNewSession()"
        />
      </div>

      <!-- 会话列表 -->
      <div class="session-list">
        <div
          v-for="session in chatStore.sessions"
          :key="session.id"
          class="session-item"
          :class="{ active: session.id === chatStore.currentConversationId }"
          @click="chatStore.switchSession(session.id)"
        >
          <el-icon :size="14" class="session-icon"><ChatDotSquare /></el-icon>
          <div class="session-info">
            <span class="session-title">{{ session.title }}</span>
            <span class="session-preview" v-if="session.lastMessage">{{ session.lastMessage }}</span>
          </div>
        </div>

        <div v-if="chatStore.sessions.length === 0" class="session-empty">
          暂无对话，点击 + 新建
        </div>
      </div>
    </div>

    <!-- ===== 右侧对话主区域 ===== -->
    <div class="chat-main">
      <!-- 对话顶部工具栏 -->
      <div class="chat-toolbar">
        <div class="toolbar-left">
          <span class="conversation-title">{{ chatStore.currentTitle }}</span>
          <span class="message-count" v-if="chatStore.hasMessages">
            {{ chatStore.messages.length }} 条消息
          </span>
        </div>
        <div class="toolbar-right">
          <!-- 流式模式切换 -->
          <div class="stream-toggle">
            <span class="toggle-label">流式回复</span>
            <el-switch 
              :model-value="chatStore.useStreamMode" 
              @change="val => chatStore.useStreamMode = val as boolean"
              size="small" 
            />
          </div>
          <!-- 模型选择 -->
          <el-input
            v-model="chatStore.currentModel"
            placeholder="模型名"
            size="small"
            style="width: 140px"
            clearable
          />
          <!-- 清空按钮 -->
          <el-button
            size="small"
            type="danger"
            text
            :icon="Delete"
            @click="handleClearChat"
            :disabled="!chatStore.hasMessages"
            title="清空对话历史"
          >
            清空对话
          </el-button>
        </div>
      </div>

      <!-- 消息列表区域 -->
      <div ref="messagesContainer" class="messages-container">
        <!-- 空状态：引导用户提问 -->
        <div v-if="!chatStore.hasMessages" class="empty-state">
          <div class="empty-icon">
            <svg viewBox="0 0 80 80" fill="none">
              <circle cx="40" cy="40" r="38" fill="url(#empty-grad)" opacity="0.15"/>
              <path d="M25 35h30M25 45h20" stroke="#7c3aed" stroke-width="3" stroke-linecap="round"/>
              <defs>
                <linearGradient id="empty-grad" x1="0" y1="0" x2="80" y2="80">
                  <stop stop-color="#7c3aed"/><stop offset="1" stop-color="#06b6d4"/>
                </linearGradient>
              </defs>
            </svg>
          </div>
          <p class="empty-title">开始你的 AI 对话</p>
          <p class="empty-desc">支持多轮上下文记忆、Markdown 渲染、代码高亮</p>
          <!-- 快捷示例问题 -->
          <div class="quick-prompts">
            <button
              v-for="prompt in quickPrompts"
              :key="prompt"
              class="quick-prompt-btn"
              @click="handleSend(prompt)"
            >
              {{ prompt }}
            </button>
          </div>
        </div>

        <!-- 消息气泡列表 -->
        <div
          v-for="message in chatStore.messages"
          :key="message.id"
          class="message-wrapper message-animate"
          :class="message.role"
        >
          <!-- 头像 -->
          <div v-if="message.role === 'assistant'" class="avatar ai-avatar">
            <svg viewBox="0 0 24 24" fill="none">
              <rect width="24" height="24" rx="6" fill="url(#ai-grad)"/>
              <path d="M6 17L9 7L12 14L15 7L18 17" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              <defs>
                <linearGradient id="ai-grad" x1="0" y1="0" x2="24" y2="24">
                  <stop stop-color="#7c3aed"/><stop offset="1" stop-color="#06b6d4"/>
                </linearGradient>
              </defs>
            </svg>
          </div>
          <!-- 用户头像 -->
          <div v-if="message.role === 'user'" class="avatar user-avatar">
            <el-icon :size="14"><User /></el-icon>
          </div>

          <!-- 消息气泡 -->
          <div class="message-bubble" :class="{ error: message.isError }">
            <!-- 用户消息：纯文本 -->
            <div v-if="message.role === 'user'" class="message-text">{{ message.content }}</div>

            <!-- AI 消息：Markdown 渲染 -->
            <div v-else class="message-content">
              <template v-if="message.isLoading && !message.content">
                <!-- 加载中：三点动画 -->
                <div class="typing-dots">
                  <span></span><span></span><span></span>
                </div>
              </template>
              <template v-else>
                <MarkdownRenderer :content="message.content" />
                <!-- 流式输出时显示光标 -->
                <span v-if="message.isLoading" class="typing-cursor"></span>
              </template>
            </div>

            <!-- 消息时间 -->
            <div class="message-time">
              {{ formatTime(message.timestamp) }}
            </div>
          </div>

        </div>
      </div>

      <!-- 输入区域 -->
      <div class="input-area">
        <div class="input-wrapper">
          <el-input
            v-model="inputText"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 6 }"
            placeholder="输入消息，Shift+Enter 换行，Enter 发送..."
            :disabled="chatStore.isSending"
            @keydown.enter.exact.prevent="handleSend()"
            resize="none"
            style="flex: 1"
          />
          <button
            class="send-btn"
            :class="{ sending: chatStore.isSending }"
            :disabled="!inputText.trim() || chatStore.isSending"
            @click="handleSend()"
          >
            <el-icon :size="18" v-if="!chatStore.isSending"><Promotion /></el-icon>
            <el-icon :size="18" v-else class="loading-spin"><Loading /></el-icon>
          </button>
        </div>
        <div class="input-hint">
          <span v-if="chatStore.isSending" class="hint-sending">AI 正在思考中...</span>
          <span v-else>Enter 发送 · Shift+Enter 换行</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted } from 'vue'
import { Plus, Delete, User, Promotion, Loading, ChatDotSquare } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useChatStore } from '@/stores/chat'
import { sendChat, sendStreamChat, clearConversation } from '@/api/modules/chat'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'

const chatStore = useChatStore()
const messagesContainer = ref<HTMLElement | null>(null)
const inputText = ref<string>('')

// 快捷示例问题
const quickPrompts = [
  '你好！介绍一下你能做什么？',
  '帮我写一段 Python 冒泡排序代码',
  '今天有什么日期？算一算 365 天后是哪天？',
  '用 Markdown 格式写一个项目说明表格',
]

/**
 * 格式化时间戳为 HH:mm:ss 格式
 */
function formatTime(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/**
 * 滚动消息区域到底部（每次消息更新时调用）
 */
async function scrollToBottom(): Promise<void> {
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

/**
 * 发送消息主逻辑
 * 支持普通模式和流式模式两种方式
 */
async function handleSend(text?: string): Promise<void> {
  const content = (text || inputText.value).trim()
  if (!content) return
  if (chatStore.isSending) return

  // 如果没有当前会话，先创建一个
  if (!chatStore.currentConversationId) {
    chatStore.createNewSession()
  }

  inputText.value = ''
  chatStore.isSending = true

  // 1. 添加用户消息
  chatStore.addUserMessage(content)
  await scrollToBottom()

  // 2. 添加 AI 占位消息
  const aiMessage = chatStore.addAssistantPlaceholder()
  await scrollToBottom()

  const requestData = {
    conversation_id: chatStore.currentConversationId,
    message: content,
    model: chatStore.currentModel || undefined,
  }

  try {
    if (chatStore.useStreamMode) {
      // ======= 流式模式：逐字接收 =======
      console.log('[对话] 使用流式模式发送消息')
      await sendStreamChat(
        requestData,
        (chunk) => {
          // 每收到一段流数据，追加到消息内容
          chatStore.appendToMessage(aiMessage.id, chunk)
          scrollToBottom()
        },
        () => {
          // 流结束
          chatStore.finalizeMessage(aiMessage.id)
          chatStore.isSending = false
          console.log('[对话] 流式消息完成')
        },
        (error) => {
          // 流错误
          chatStore.markMessageError(aiMessage.id, `网络错误：${error.message}`)
          chatStore.isSending = false
          ElMessage.error('流式对话发生错误，请重试')
        }
      )
    } else {
      // ======= 普通模式：一次性返回 =======
      console.log('[对话] 使用普通模式发送消息')
      const result = await sendChat(requestData)
      chatStore.appendToMessage(aiMessage.id, result.message)
      chatStore.finalizeMessage(aiMessage.id)
      chatStore.isSending = false
      await scrollToBottom()
    }
  } catch (error) {
    const errMsg = error instanceof Error ? error.message : '请求失败'
    chatStore.markMessageError(aiMessage.id, `发生错误：${errMsg}`)
    chatStore.isSending = false
    console.error('[对话] 发送消息失败:', error)
  }
}

/**
 * 清空当前会话对话历史
 * 同时调用后端接口清空服务端短期记忆
 */
async function handleClearChat(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '确定要清空当前对话的所有消息吗？此操作将同时清除服务端记忆，无法恢复。',
      '清空确认',
      { confirmButtonText: '确定清空', cancelButtonText: '取消', type: 'warning' }
    )

    // 调用后端接口清空服务端短期记忆
    await clearConversation(chatStore.currentConversationId)

    // 清空前端消息列表
    chatStore.clearCurrentMessages()
    console.log('[对话] 已清空会话:', chatStore.currentConversationId)
    ElMessage.success('对话历史已清空')
  } catch {
    // 用户点击取消时 ElMessageBox 会 reject，这里忽略即可
  }
}

// 初始化：确保有一个默认会话
onMounted(() => {
  chatStore.init()
  console.log('[ChatView] 对话页面已挂载，当前会话ID:', chatStore.currentConversationId)
})
</script>

<style scoped>
.chat-view {
  display: flex;
  height: 100%;
  background: var(--color-bg-secondary);
  overflow: hidden;
}

/* ====== 左侧对话列表 ====== */
.chat-sidebar {
  width: 220px;
  min-width: 220px;
  height: 100%;
  background: var(--color-bg-primary);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.chat-sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid var(--color-border-light);
}

.sidebar-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.session-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast);
  margin-bottom: 2px;
}

.session-item:hover {
  background: var(--color-bg-hover);
}

.session-item.active {
  background: var(--color-primary-lighter);
}

.session-icon {
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.session-item.active .session-icon {
  color: var(--color-primary);
}

.session-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.session-title {
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-preview {
  font-size: 0.7rem;
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-empty {
  text-align: center;
  padding: 32px 16px;
  font-size: 0.8rem;
  color: var(--color-text-muted);
}

/* ====== 右侧主对话区 ====== */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

/* 工具栏 */
.chat-toolbar {
  padding: 10px 20px;
  background: var(--color-bg-primary);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.conversation-title {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--color-text-primary);
}

.message-count {
  font-size: 0.72rem;
  color: var(--color-text-muted);
  background: var(--color-bg-secondary);
  padding: 2px 8px;
  border-radius: var(--radius-full);
  border: 1px solid var(--color-border);
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.stream-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
}

.toggle-label {
  font-size: 0.8rem;
  color: var(--color-text-secondary);
  white-space: nowrap;
}

/* 消息列表容器 */
.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 24px 20px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

/* 空状态 */
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 60px 24px;
  gap: 12px;
}

.empty-icon svg {
  width: 80px;
  height: 80px;
}

.empty-title {
  font-family: var(--font-heading);
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--color-text-primary);
}

.empty-desc {
  font-size: 0.85rem;
  color: var(--color-text-muted);
}

.quick-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-top: 8px;
  max-width: 600px;
}

.quick-prompt-btn {
  padding: 8px 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  color: var(--color-text-secondary);
  font-size: 0.8rem;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.quick-prompt-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-lighter);
}

/* ====== 消息气泡 ====== */
.message-wrapper {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  max-width: 90%;
}

.message-wrapper.user {
  flex-direction: row-reverse;
  align-self: flex-end;
}

.message-wrapper.assistant {
  align-self: flex-start;
}

/* 头像 */
.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ai-avatar svg {
  width: 32px;
  height: 32px;
}

.user-avatar {
  background: var(--gradient-primary);
  color: white;
}

/* 气泡主体 */
.message-bubble {
  position: relative;
  max-width: 100%;
}

/* 用户消息气泡 */
.user .message-bubble {
  background: var(--gradient-primary);
  color: white;
  padding: 12px 16px;
  border-radius: 16px 4px 16px 16px;
}

/* AI 消息气泡 */
.assistant .message-bubble {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  padding: 12px 16px;
  border-radius: 4px 16px 16px 16px;
  box-shadow: var(--shadow-card);
}

.message-bubble.error {
  border-color: var(--color-danger) !important;
  background: #fef2f2 !important;
}

.message-text {
  font-size: 0.875rem;
  line-height: 1.6;
  word-break: break-word;
  white-space: pre-wrap;
}

.message-content {
  min-width: 20px;
}

.message-time {
  font-size: 0.65rem;
  color: rgba(255,255,255,0.6);
  margin-top: 4px;
  text-align: right;
}

.assistant .message-time {
  color: var(--color-text-muted);
  text-align: left;
}

/* 三点加载动画 */
.typing-dots {
  display: flex;
  gap: 5px;
  padding: 4px 0;
  align-items: center;
  height: 24px;
}

.typing-dots span {
  width: 7px;
  height: 7px;
  background: var(--color-primary);
  border-radius: 50%;
  animation: typing-bounce 1.2s ease infinite;
}

.typing-dots span:nth-child(2) { animation-delay: 0.2s; }
.typing-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes typing-bounce {
  0%, 100% { transform: translateY(0); opacity: 0.4; }
  50% { transform: translateY(-5px); opacity: 1; }
}

/* 打字机光标 */
.typing-cursor::after {
  content: '▋';
  display: inline-block;
  color: var(--color-primary);
  animation: blink-cursor 1s step-end infinite;
  font-size: 0.85em;
}

@keyframes blink-cursor {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* ====== 输入区域 ====== */
.input-area {
  padding: 12px 20px 16px;
  background: var(--color-bg-primary);
  border-top: 1px solid var(--color-border);
  flex-shrink: 0;
}

.input-wrapper {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}

.input-wrapper :deep(.el-textarea__inner) {
  border-radius: var(--radius-md);
  resize: none;
  font-size: 0.875rem;
  padding: 10px 14px;
  font-family: var(--font-body);
  line-height: 1.6;
  border-color: var(--color-border);
  transition: border-color var(--transition-fast);
}

.input-wrapper :deep(.el-textarea__inner:focus) {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.1);
}

/* 发送按钮 */
.send-btn {
  width: 42px;
  height: 42px;
  border-radius: var(--radius-md);
  border: none;
  background: var(--gradient-primary);
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: opacity var(--transition-fast), transform var(--transition-fast);
  box-shadow: var(--shadow-md);
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}

.send-btn:not(:disabled):hover {
  opacity: 0.9;
  transform: scale(1.05);
}

.loading-spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.input-hint {
  font-size: 0.7rem;
  color: var(--color-text-muted);
  margin-top: 6px;
  padding-left: 2px;
}

.hint-sending {
  color: var(--color-primary);
  font-weight: 500;
}
</style>
