/**
 * Chat 对话相关 API 接口封装
 * 对接后端 /api/v1/chat 路由
 */
import { httpPost, httpDelete, fetchStream } from '@/api/request'
import type { ChatRequest, ChatResponse } from '@/types/chat'

/**
 * 发起普通对话（一次性返回完整回复）
 * POST /api/v1/chat
 */
export function sendChat(data: ChatRequest): Promise<ChatResponse> {
  console.log('[Chat API] 发起普通对话，会话ID:', data.conversation_id)
  return httpPost<ChatResponse>('/chat', data)
}

/**
 * 发起流式对话（逐字返回，打字机效果）
 * POST /api/v1/chat/stream
 * 后端返回 text/plain 流，使用 fetch ReadableStream 读取
 *
 * @param data - 对话请求参数
 * @param onChunk - 每收到新 chunk 时的回调
 * @param onDone - 流结束时的回调
 * @param onError - 发生错误时的回调
 */
export function sendStreamChat(
  data: ChatRequest,
  onChunk: (chunk: string) => void,
  onDone?: () => void,
  onError?: (error: Error) => void
): Promise<void> {
  console.log('[Chat API] 发起流式对话，会话ID:', data.conversation_id)
  return fetchStream('/chat/stream', data, onChunk, onDone, onError)
}

/**
 * 清空指定会话的对话历史
 * DELETE /api/v1/chat/{conversation_id}
 */
export function clearConversation(conversationId: string): Promise<{ conversation_id: string; status: string }> {
  console.log('[Chat API] 清空会话历史，会话ID:', conversationId)
  return httpDelete(`/chat/${conversationId}`)
}
