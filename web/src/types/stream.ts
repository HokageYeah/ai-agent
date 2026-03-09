// src/types/stream.ts

// 流式事件类型定义
export interface StreamEvent {
  event: string
  iteration: number
  step_index?: number
  step_total?: number
  data?: any
  error?: string
  timestamp: number
}

// 为更复杂的执行结果定义内部便捷接口以在模板中使用
export interface StepResult {
  action: string;
  success: boolean;
  tool_name?: string;
  skill_id?: string;
  agent_id?: string;
  error?: string;
  result: any;
}

export interface ReflectionResult {
  success: boolean;
  needs_replanning: boolean;
  feedback: string;
  summary: string;
}

export interface ParsedExecuteResult {
  step_results?: StepResult[];
  reflection?: ReflectionResult;
  [key: string]: any;
}

/** 按主/子 Agent 划分的独立控制区块 */
export interface AgentBlock {
  type: 'main' | 'sub';
  id: string; // 'main-xxx' 或 sub_agent_id
  name: string; // 主Agent名称或子Agent名称
  task: string | null;
  events: StreamEvent[];
}

/** 单个扁平化试图的节点，用于轨迹展示的纯缩进树结构 */
export interface TrajectoryNode {
  id: string;          // 唯一标识 (如 iter-0, block-1, event-2)
  level: number;       // 缩进层级 (0: 迭代, 1: 阶段, 2: 动作, 3+: 子 Agent 等)
  type: string;        // 'iteration' | 'phase' | 'event' | 'sub_agent' 
  title?: string;      // 标题
  isParent: boolean;   // 是否含有子节点 (决定是否可折叠显示 >)
  isExpanded: boolean; // 是否当前展开
  event?: StreamEvent; // 关联的原始事件 (针对 action 层级)
  children?: TrajectoryNode[]; // 子节点，如果在生成时构建成树
}

export type ExecutionPhase = 'idle' | 'planning' | 'executing' | 'reflecting' | 'completed'
