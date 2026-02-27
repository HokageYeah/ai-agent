/**
 * Agent 相关 API 接口封装
 * 对接后端 /api/v1/agents 路由
 */
import { httpGet, httpPost } from '@/api/request'
import type {
  AgentInfo,
  AgentDetail,
  AgentExecuteRequest,
  AgentExecuteResponse
} from '@/types/agent'

/**
 * 获取所有可用 Agent 列表
 * GET /api/v1/agents
 */
export function getAgentList(): Promise<AgentInfo[]> {
  console.log('[Agent API] 获取 Agent 列表')
  return httpGet<AgentInfo[]>('/agents')
}

/**
 * 获取指定 Agent 的详细信息
 * GET /api/v1/agents/{agent_id}
 */
export function getAgentDetail(agentId: string): Promise<AgentDetail> {
  console.log('[Agent API] 获取 Agent 详情，agentId:', agentId)
  return httpGet<AgentDetail>(`/agents/${agentId}`)
}

/**
 * 执行指定 Agent 完成任务
 * POST /api/v1/agents/{agent_id}/execute
 *
 * @param agentId - Agent ID
 * @param data - 执行请求参数（任务描述、可选配置）
 */
export function executeAgent(agentId: string, data: AgentExecuteRequest): Promise<AgentExecuteResponse> {
  console.log('[Agent API] 执行 Agent，agentId:', agentId, '任务:', data.task)
  return httpPost<AgentExecuteResponse>(`/agents/${agentId}/execute`, data)
}

/**
 * 流式执行 Agent 完成任务（SSE - Server-Sent Events）
 * POST /api/v1/agents/{agent_id}/execute/stream
 *
 * 后端使用 FastAPI StreamingResponse 推送 text/event-stream 格式的事件流。
 * 前端使用 fetch + ReadableStream 实现 POST 请求的流式读取。
 *
 * SSE 协议格式（每个消息之间以 \n\n 分隔）：
 *   data: {"event": "plan_start", ...}\n\n
 *   data: {"event": "plan_complete", ...}\n\n
 *   ...
 *
 * 支持的事件类型（按执行顺序）：
 *   plan_start → plan_complete → step_start
 *   → tool_complete/skill_complete/delegate_complete (多次)
 *   → execute_complete → reflection_start → reflection_complete
 *   → final_answer → complete / error
 *
 * @param agentId - Agent ID
 * @param data - 执行请求参数（任务描述、可选配置）
 * @param onMessage - 收到任意事件时的回调函数
 * @param onError - 发生错误时的回调函数
 * @param onComplete - 收到 complete 事件时的回调函数
 * @returns 包含 close() 方法的控制对象（用于提前中断连接）
 */
export function executeAgentStream(
  agentId: string,
  data: AgentExecuteRequest,
  onMessage: (event: any) => void,
  onError?: (error: any) => void,
  onComplete?: (data: any) => void
): EventSource {
  console.log('[Agent API] 开始流式执行，agentId:', agentId, '| 任务:', data.task.slice(0, 80))
  
  // SSE 端点 URL（POST 方式，不能用 EventSource 原生 API）
  const url = `/api/v1/agents/${agentId}/execute/stream`
  
  // AbortController 用于提前关闭连接
  const controller = new AbortController()
  let eventCount = 0
  
  fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      // 告知服务端我们期望 SSE 格式
      'Accept': 'text/event-stream',
      // 禁用缓存，确保每次都建立新连接
      'Cache-Control': 'no-cache'
    },
    body: JSON.stringify({
      task: data.task,
      conversation_history: data.conversation_history || [],
      config: data.config || {}
    }),
    signal: controller.signal
  }).then(response => {
    if (!response.ok) {
      const err = new Error(`HTTP 请求失败: ${response.status} ${response.statusText}`)
      console.error('[Agent API] 请求失败:', err.message)
      if (onError) onError(err)
      return
    }
    
    console.log('[Agent API] 连接建立成功，开始读取事件流...')
    
    const reader = response.body?.getReader()
    if (!reader) {
      const err = new Error('Response body 为 null，无法读取流')
      console.error('[Agent API]', err.message)
      if (onError) onError(err)
      return
    }
    
    // TextDecoder 用于将 Uint8Array 解码为字符串（支持多字节字符如中文）
    const decoder = new TextDecoder('utf-8')
    
    /**
     * SSE Buffer 管理器
     * 
     * SSE 协议：服务端以 "data: ...\n\n" 格式发送消息。
     * 由于网络分包，单次 read() 可能只收到消息的一部分。
     * 需要将 chunk 累加到 buffer，遇到完整消息（以 \n\n 结尾）才解析。
     * 
     * 正确的分隔逻辑：按 \n\n 切分，而不是按 \n 切分，
     * 这样可以避免因行内容不完整而丢失数据。
     */
    let buffer = ''
    
    /**
     * 从 buffer 中解析所有完整的 SSE 消息
     * 
     * SSE 消息以 \n\n 为结束标记。
     * 每个消息内部可能有多行（以 \n 分隔），我们只处理 "data:" 行。
     * 
     * @returns 未处理完的剩余 buffer（不完整的消息）
     */
    function flushBuffer(): void {
      // 按 \n\n 分割，得到可能完整的 SSE 消息块
      // 最后一个元素可能是不完整的（等待下一个 chunk）
      const parts = buffer.split('\n\n')
      
      // 保留最后一个可能不完整的部分（无论是否为空都保留）
      buffer = parts.pop() ?? ''
      
      // 处理所有完整的消息块
      for (const part of parts) {
        const trimmedPart = part.trim()
        if (!trimmedPart) continue
        
        // 在每个消息块中查找 "data:" 行
        // 标准 SSE 消息每行以 "\n" 分隔，我们逐行查找 "data:" 开头的行
        const lines = trimmedPart.split('\n')
        for (const line of lines) {
          const trimmedLine = line.trim()
          
          if (!trimmedLine.startsWith('data:')) continue
          
          // 提取 data 内容（"data: {...}" → "{...}"）
          // 注意：data: 后面可能有空格，也可能没有，兼容两种格式
          const dataStr = trimmedLine.slice(5).trimStart()
          
          if (!dataStr) continue
          
          try {
            const event = JSON.parse(dataStr)
            eventCount++
            
            console.log(
              `[Agent API] 事件 #${eventCount}: ${event.event}`,
              `| 迭代: ${event.iteration ?? '-'}`,
              event.step_index !== undefined ? `| 步骤: ${event.step_index}/${event.step_total}` : '',
              event.data ? '| 有数据' : ''
            )
            
            // 调用外部消息回调（触发 Vue 响应式更新）
            onMessage(event)
            
            // complete 事件：额外调用完成回调
            if (event.event === 'complete' && onComplete) {
              console.log('[Agent API] 收到 complete 事件，调用完成回调')
              onComplete(event.data)
            }
          } catch (parseErr) {
            // JSON 解析失败：记录错误但不中断流，继续读取后续事件
            console.error(
              '[Agent API] JSON 解析失败，跳过此消息:',
              parseErr,
              '\n原始数据:', dataStr.slice(0, 200)
            )
          }
        }
      }
    }
    
    /**
     * 递归读取流
     * 每次 read() 获取下一个数据块，解码后追加到 buffer 并尝试解析消息。
     */
    function read() {
      reader.read().then(({ done, value }) => {
        if (done) {
          // 流结束：处理 buffer 中剩余的内容
          if (buffer.trim()) {
            console.log('[Agent API] 流结束，处理剩余 buffer，长度:', buffer.length)
            // 将剩余 buffer 当作完整消息尝试解析
            buffer += '\n\n'  // 补充结束标记
            flushBuffer()
          }
          console.log(`[Agent API] 流式执行完成，共处理 ${eventCount} 个事件`)
          return
        }
        
        // 将新数据块（Uint8Array）解码为字符串并追加到 buffer
        // stream: true 参数确保多字节字符（如中文）跨块时能正确解码
        const chunk = decoder.decode(value, { stream: true })
        buffer += chunk
        
        // 尝试从 buffer 中解析完整消息
        flushBuffer()
        
        // 继续读取下一个数据块
        read()
      }).catch(error => {
        if (error.name === 'AbortError') {
          console.log('[Agent API] 流式连接已被手动中止')
          return
        }
        console.error('[Agent API] 读取流数据失败:', error)
        if (onError) onError(error)
      })
    }
    
    // 启动读取循环
    read()
    
  }).catch(error => {
    if (error.name === 'AbortError') {
      console.log('[Agent API] fetch 请求已被中止')
      return
    }
    console.error('[Agent API] 发起流式请求失败:', error)
    if (onError) onError(error)
  })
  
  // 返回控制对象（模拟 EventSource 接口，提供 close() 方法）
  return {
    close: () => {
      console.log('[Agent API] 手动关闭流式连接')
      controller.abort()
    }
  } as EventSource
}

/**
 * 使用 EventSource 原生 API 进行流式请求（GET 方式）
 * 注意：后端需要支持 GET 方式的 SSE
 * 
 * @deprecated 建议使用 executeAgentStream 函数
 */
export function executeAgentStreamWithEventSource(
  agentId: string,
  data: AgentExecuteRequest,
  onMessage: (event: any) => void,
  onError?: (error: any) => void,
  onComplete?: (data: any) => void
): EventSource {
  console.log('[Agent API] 使用 EventSource 流式执行 Agent，agentId:', agentId)
  
  // 将请求数据转换为 URL 参数
  const params = new URLSearchParams()
  params.append('task', data.task)
  if (data.conversation_history) {
    params.append('conversation_history', JSON.stringify(data.conversation_history))
  }
  if (data.config) {
    params.append('config', JSON.stringify(data.config))
  }
  
  const url = `/api/v1/agents/${agentId}/execute/stream?${params.toString()}`
  const eventSource = new EventSource(url)
  
  eventSource.onmessage = (e) => {
    try {
      const event = JSON.parse(e.data)
      console.log('[Agent API] EventSource 收到事件:', event.event)
      onMessage(event)
      
      if (event.event === 'complete' && onComplete) {
        onComplete(event.data)
      }
    } catch (error) {
      console.error('[Agent API] 解析事件失败:', error)
    }
  }
  
  eventSource.onerror = (e) => {
    console.error('[Agent API] EventSource 错误:', e)
    if (onError) onError(e)
    eventSource.close()
  }
  
  return eventSource
}
