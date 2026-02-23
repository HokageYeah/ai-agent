/**
 * 工作流相关 API 接口封装
 * 对接后端 /api/v1/workflows 路由
 */
import { httpGet, httpPost } from '@/api/request'
import type {
  WorkflowInfo,
  WorkflowExecuteRequest,
  WorkflowExecuteResponse
} from '@/types/agent'

/**
 * 获取所有工作流列表
 * GET /api/v1/workflows
 */
export function getWorkflowList(): Promise<WorkflowInfo[]> {
  console.log('[Workflows API] 获取工作流列表')
  return httpGet<WorkflowInfo[]>('/workflows')
}

/**
 * 执行指定工作流
 * POST /api/v1/workflows/{workflow_id}/execute
 *
 * @param workflowId - 工作流 ID
 * @param data - 工作流输入数据
 */
export function executeWorkflow(workflowId: string, data: WorkflowExecuteRequest): Promise<WorkflowExecuteResponse> {
  console.log('[Workflows API] 执行工作流，workflowId:', workflowId, '输入:', data.input_data)
  return httpPost<WorkflowExecuteResponse>(`/workflows/${workflowId}/execute`, data)
}
