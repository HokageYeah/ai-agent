/**
 * Automation 自动化服务 API 接口封装
 * 对接后端 /api/v1/automation 路由
 */
import { httpGet, httpPost } from '@/api/request'
import type {
  AutomationServiceInfo,
  DataProcessingRequest,
  ReportGenerationRequest,
  CodeGenerationRequest,
  AutomationResponse
} from '@/types/automation'

/**
 * 获取自动化服务列表（含参数元数据）
 * GET /api/v1/automation/services
 */
export function getAutomationServices(): Promise<AutomationServiceInfo[]> {
  console.log('[Automation API] 获取服务列表')
  return httpGet<AutomationServiceInfo[]>('/automation/services')
}

/**
 * 数据处理自动化
 * POST /api/v1/automation/data-processing
 */
export function dataProcessing(data: DataProcessingRequest): Promise<AutomationResponse> {
  console.log('[Automation API] 数据处理请求', data)
  return httpPost<AutomationResponse>('/automation/data-processing', data)
}

/**
 * 报告生成自动化
 * POST /api/v1/automation/report-generation
 */
export function reportGeneration(data: ReportGenerationRequest): Promise<AutomationResponse> {
  console.log('[Automation API] 报告生成请求', data)
  return httpPost<AutomationResponse>('/automation/report-generation', data)
}

/**
 * 代码生成自动化
 * POST /api/v1/automation/code-generation
 */
export function codeGeneration(data: CodeGenerationRequest): Promise<AutomationResponse> {
  console.log('[Automation API] 代码生成请求', data)
  return httpPost<AutomationResponse>('/automation/code-generation', data)
}
