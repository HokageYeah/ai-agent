/**
 * API 通用响应类型定义
 * 对应后端 ApiResponseData 统一响应格式
 */

// 后端统一响应包装结构
export interface ApiResponseData<T = unknown> {
  platform: string
  api: string
  data: T
  ret: string[]
  v: number
}

// 分页信息（备用）
export interface PaginationInfo {
  page: number
  pageSize: number
  total: number
}
