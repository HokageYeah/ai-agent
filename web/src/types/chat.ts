/**
 * 对话相关类型定义
 * 对应后端 Chat API 的请求和响应格式
 */

// 消息角色枚举
export type MessageRole = 'user' | 'assistant' | 'system'

// 单条消息
export interface ChatMessage {
  id: string                  // 前端生成的唯一 ID，用于列表渲染
  role: MessageRole           // 消息角色
  content: string             // 消息内容（支持 Markdown）
  timestamp: number           // 时间戳（毫秒）
  isLoading?: boolean         // 是否正在加载（流式输出时）
  isError?: boolean           // 是否发生错误
}

// 对话请求（POST /api/v1/chat）
export interface ChatRequest {
  conversation_id: string       // 会话 ID，用于多轮对话上下文
  message: string               // 用户输入的消息
  model?: string                // 模型名称，可选
  system_prompt?: string        // 系统提示词，可选
  temperature?: number          // 温度参数，可选
  max_tokens?: number           // 最大输出 token 数，可选
}

// 对话响应（来自后端 ChatResponse 的 data 字段）
export interface ChatResponse {
  conversation_id: string       // 会话 ID
  message: string               // AI 回复内容
  model: string                 // 实际使用的模型
  usage?: {                     // Token 使用情况
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
  }
}

// 会话列表项
export interface ConversationSession {
  id: string                    // 会话 ID
  title: string                 // 会话标题（取第一条消息作为标题）
  lastMessage: string           // 最后一条消息摘要
  updatedAt: number             // 最后更新时间
  messageCount: number          // 消息数量
}
