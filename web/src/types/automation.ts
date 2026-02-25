/**
 * Automation 自动化服务类型定义
 * 对应后端 app/schemas/automation_data.py 的数据模型
 */

/**
 * 自动化服务参数元数据
 */
export interface AutomationParamSchema {
  label: string
  description: string
  examples: string[]
  required: boolean
}

/**
 * 自动化服务信息
 */
export interface AutomationServiceInfo {
  type: string
  name: string
  description: string
  icon: string
  color: string
  param_schemas: Record<string, AutomationParamSchema>
}

/**
 * 数据处理请求
 */
export interface DataProcessingRequest {
  data: any
  processing_config?: Record<string, any>
}

/**
 * 报告生成请求
 */
export interface ReportGenerationRequest {
  data_source: string
  template?: string
  report_config?: Record<string, any>
}

/**
 * 代码生成请求
 */
export interface CodeGenerationRequest {
  requirements: string
  language?: string
  framework?: string
  code_config?: Record<string, any>
}

/**
 * 自动化服务执行响应
 */
export interface AutomationResponse {
  success: boolean
  result?: any
  error?: string
  processing_time?: number
}

/**
 * 自动化服务类型枚举
 */
export type AutomationType = 'data_processing' | 'report_generation' | 'code_generation'

/**
 * 自动化服务选项配置（前端使用）
 */
export interface AutomationOption {
  type: AutomationType
  name: string
  description: string
  icon: string
  color: string
  param_schemas?: Record<string, AutomationParamSchema>
}
