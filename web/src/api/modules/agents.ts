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
