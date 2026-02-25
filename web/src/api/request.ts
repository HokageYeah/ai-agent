/**
 * Axios 请求封装
 * 统一处理请求配置、拦截器、错误处理
 */
import axios, { type AxiosInstance, type AxiosRequestConfig, type AxiosResponse } from 'axios'
import { ElMessage } from 'element-plus'
import type { ApiResponseData } from '@/types/api'

// 创建 Axios 实例，基础配置
const request: AxiosInstance = axios.create({
  baseURL: '/api/v1',         // 通过 Vite 代理转发到后端 localhost:8002
  timeout: 300000,            // 超时时间 300 秒（Agent 执行可能较慢）
  headers: {
    'Content-Type': 'application/json',
  },
})

// ====== 请求拦截器 ======
request.interceptors.request.use(
  (config) => {
    console.log(`[API请求] ${config.method?.toUpperCase()} ${config.url}`, config.data || config.params)
    return config
  },
  (error) => {
    console.error('[API请求错误]', error)
    return Promise.reject(error)
  }
)

// ====== 响应拦截器 ======
request.interceptors.response.use(
  (response: AxiosResponse) => {
    console.log(`[API响应] ${response.config.url}`, response.data)
    return response
  },
  (error) => {
    // 统一处理 HTTP 错误
    const status = error.response?.status
    const detail = error.response?.data?.detail || '请求失败，请稍后重试'

    console.error(`[API错误] status:${status}`, detail)

    if (status === 404) {
      ElMessage.error(`资源不存在：${detail}`)
    } else if (status === 500) {
      ElMessage.error(`服务器内部错误：${detail}`)
    } else if (error.code === 'ECONNABORTED') {
      ElMessage.error('请求超时，Agent 可能仍在处理中')
    } else {
      ElMessage.error(detail)
    }

    return Promise.reject(error)
  }
)

/**
 * 通用 GET 请求封装
 * 自动解包后端 ApiResponseData.data 字段
 */
export async function httpGet<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  const response = await request.get<ApiResponseData<T>>(url, { params })
  return response.data.data
}

/**
 * 通用 POST 请求封装
 * 自动解包后端 ApiResponseData.data 字段
 */
export async function httpPost<T>(url: string, data?: unknown): Promise<T> {
  const response = await request.post<ApiResponseData<T>>(url, data)
  return response.data.data
}

/**
 * 通用 DELETE 请求封装
 */
export async function httpDelete<T>(url: string): Promise<T> {
  const response = await request.delete<ApiResponseData<T>>(url)
  return response.data.data
}

/**
 * 流式 POST 请求（用于 SSE 流式对话）
 * 后端返回 text/plain 流，使用 fetch 而非 axios
 */
export async function fetchStream(
  url: string,
  data: unknown,
  onChunk: (chunk: string) => void,
  onDone?: () => void,
  onError?: (error: Error) => void
): Promise<void> {
  console.log('[流式请求] 开始 SSE 流式对话', url)
  try {
    const response = await fetch(`/api/v1${url}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
    })

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`)
    }

    if (!response.body) {
      throw new Error('响应体为空，无法读取流数据')
    }

    // 使用 ReadableStream 读取流式数据
    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')

    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        console.log('[流式请求] 流式数据读取完毕')
        onDone?.()
        break
      }
      // 将 Uint8Array 解码为字符串
      const chunk = decoder.decode(value, { stream: true })
      onChunk(chunk)
    }
  } catch (error) {
    const err = error instanceof Error ? error : new Error(String(error))
    console.error('[流式请求错误]', err)
    onError?.(err)
  }
}

export default request
