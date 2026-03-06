/**
 * Agent、技能、工作流相关类型定义
 * 对应后端 Agent/Skill/Workflow API 响应格式
 */

// ======================== Agent 相关 ========================

// Agent 基础信息（GET /api/v1/agents 列表返回）
export interface AgentInfo {
  agent_id: string
  name: string
  description: string
  capabilities: string[]
  available_tools: string[]
  available_skills: string[]
  child_agents: string[]
}

// Agent 详情（GET /api/v1/agents/{id} 返回额外字段）
export interface AgentDetail extends AgentInfo {
  role: string
  agent_config: {
    planning_model: string
    execution_model: string
    max_iterations: number
    timeout_seconds: number
  }
}

// 执行 Agent 的请求体（POST /api/v1/agents/{id}/execute）
export interface AgentExecuteRequest {
  task: string                          // 任务描述
  conversation_id?: string              // 可选会话 ID
  config?: Record<string, unknown>      // 可选覆盖配置
  conversation_history?: Array<{        // 可选对话历史
    role: string
    content: string
  }>
}

// 执行 Agent 的响应（data 字段）
export interface AgentExecuteResponse {
  agent_id: string
  agent_name: string
  task: string
  result: Record<string, unknown>     // 执行结果（格式根据 Agent 不同而异）
  iterations: number                   // 执行迭代次数
  success: boolean                     // 是否成功
  messages?: Record<string, any>[]     // 执行轨迹
}

// ======================== 技能相关 ========================

// 技能参数元数据（对应后端每个 prompt_template 变量的说明）
export interface SkillParamSchema {
  label: string         // 参数中文名称
  description: string   // 参数功能说明
  examples: string[]    // 示例值列表，前端可点击快捷填入
  required: boolean     // 是否必填
}

// 技能基础信息（GET /api/v1/skills 列表返回）
export interface SkillInfo {
  skill_id: string
  name: string
  description: string
  required_tools: string[]
  optional_tools: string[]
  tags: string[]
  param_schemas: Record<string, SkillParamSchema>  // 参数元数据，key 为参数名
}

// 执行技能的请求体（POST /api/v1/skills/{id}/execute）
export interface SkillExecuteRequest {
  parameters: Record<string, string>    // 模板参数键值对
  config?: Record<string, unknown>      // 可选覆盖配置
}

// 执行技能的响应（data 字段）
export interface SkillExecuteResponse {
  skill_id: string
  skill_name: string
  result: {
    content: string
    usage: unknown
  }
  success: boolean
}

// ======================== 工作流相关 ========================

// 工作流基础信息（GET /api/v1/workflows 列表返回）
export interface WorkflowInfo {
  workflow_id: string
  name: string
  description: string
  node_count: number
  entry_node: string
  exit_nodes: string[]
}

// 执行工作流的请求体（POST /api/v1/workflows/{id}/execute）
export interface WorkflowExecuteRequest {
  input_data: Record<string, unknown>   // 工作流输入数据
}

// 执行工作流的响应（data 字段）
export interface WorkflowExecuteResponse {
  workflow_id: string
  workflow_name: string
  result: Record<string, unknown>
  success: boolean
}
