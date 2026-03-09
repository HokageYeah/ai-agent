"""
AI Agent API Schema 定义
================================

本模块定义了 AI Agent 系统 API 的请求和响应数据模型。

包括：
1. Chat API 相关 Schema
2. Agent API 相关 Schema
3. Workflow API 相关 Schema
4. Skill API 相关 Schema
5. Tool API 相关 Schema

作者: AI Agent Team
创建时间: 2026-02-17
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Union
from enum import Enum


# =============================================================================
# Chat API Schema
# =============================================================================

class ChatRequest(BaseModel):
    """对话请求"""
    conversation_id: str = Field(..., description="会话 ID")
    message: str = Field(..., description="用户消息内容")
    system_prompt: Optional[str] = Field(None, description="系统提示词（可选）")
    model: Optional[str] = Field("qwen3-max", description="使用的模型")
    temperature: Optional[float] = Field(0.7, description="温度参数")
    max_tokens: Optional[int] = Field(2048, description="最大生成 tokens")


class ChatResponse(BaseModel):
    """对话响应"""
    conversation_id: str = Field(..., description="会话 ID")
    message: str = Field(..., description="AI 回复内容")
    model: str = Field(..., description="使用的模型")
    usage: Optional[Dict[str, Any]] = Field(None, description="Token 使用情况")


# =============================================================================
# Agent API Schema
# =============================================================================

class AgentExecuteRequest(BaseModel):
    """Agent 执行请求"""
    task: str = Field(..., description="要执行的任务描述")
    
    # NOTE: conversation_id 是跨任务“会话级”记忆的唯一标识符。
    # 当用户连续在同一个聊天窗口下发多个任务时，前端需传入此 ID。
    # 后端会根据此 ID 检索历史任务的执行摘要，并在规划阶段注入给 LLM，
    # 使其能感知到上一项任务结论，避免重复调用工具或忘记上下文要素。
    conversation_id: Optional[str] = Field(
        None, 
        description="会话 ID（用于实现跨任务的会话级上下文和记忆衔接）"
    )
    
    conversation_history: Optional[List[Dict[str, str]]] = Field(
        default_factory=list,
        description="对话历史记录"
    )
    config: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="额外配置参数"
    )


class AgentExecuteResponse(BaseModel):
    """Agent 执行响应"""
    agent_id: str = Field(..., description="Agent ID")
    agent_name: str = Field(..., description="Agent 名称")
    task: str = Field(..., description="执行的任务")
    result: Dict[str, Any] = Field(..., description="执行结果")
    iterations: int = Field(..., description="执行迭代次数")
    success: bool = Field(..., description="是否执行成功")
    messages: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="执行过程中的消息轨迹")


class AgentInfo(BaseModel):
    """Agent 信息"""
    agent_id: str = Field(..., description="Agent ID")
    name: str = Field(..., description="Agent 名称")
    description: str = Field(..., description="Agent 描述")
    capabilities: List[str] = Field(..., description="能力列表")
    available_tools: List[str] = Field(..., description="可用工具列表")
    available_skills: List[str] = Field(..., description="可用技能列表")
    child_agents: List[str] = Field(default_factory=list, description="子 Agent 列表")
    # NOTE: 示例任务列表，供前端展示快捷示例标签
    examples: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="示例任务列表，每个示例包含 label、content、style 字段"
    )


class AgentDetail(BaseModel):
    """Agent 详细信息"""
    agent_id: str = Field(..., description="Agent ID")
    name: str = Field(..., description="Agent 名称")
    description: str = Field(..., description="Agent 描述")
    role: str = Field(..., description="角色定义")
    capabilities: List[str] = Field(..., description="能力列表")
    available_tools: List[str] = Field(..., description="可用工具列表")
    available_skills: List[str] = Field(..., description="可用技能列表")
    child_agents: List[str] = Field(default_factory=list, description="子 Agent 列表")
    agent_config: Dict[str, Any] = Field(..., description="Agent 配置")


# =============================================================================
# Workflow API Schema
# =============================================================================

class WorkflowExecuteRequest(BaseModel):
    """工作流执行请求"""
    input_data: Dict[str, Any] = Field(..., description="工作流输入数据")
    config: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="额外配置参数"
    )


class WorkflowExecuteResponse(BaseModel):
    """工作流执行响应"""
    workflow_id: str = Field(..., description="工作流 ID")
    workflow_name: str = Field(..., description="工作流名称")
    result: Dict[str, Any] = Field(..., description="执行结果")
    success: bool = Field(..., description="是否执行成功")


class WorkflowInfo(BaseModel):
    """工作流信息"""
    workflow_id: str = Field(..., description="工作流 ID")
    name: str = Field(..., description="工作流名称")
    description: str = Field(..., description="工作流描述")
    node_count: int = Field(..., description="节点数量")
    entry_node: str = Field(..., description="入口节点")
    exit_nodes: List[str] = Field(..., description="出口节点列表")


# =============================================================================
# Skill API Schema
# =============================================================================

class SkillExecuteRequest(BaseModel):
    """技能执行请求"""
    parameters: Dict[str, Any] = Field(..., description="技能执行参数")
    config: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="额外配置参数"
    )


class SkillExecuteResponse(BaseModel):
    """技能执行响应"""
    skill_id: str = Field(..., description="技能 ID")
    skill_name: str = Field(..., description="技能名称")
    result: Dict[str, Any] = Field(..., description="执行结果")
    success: bool = Field(..., description="是否执行成功")


class SkillParamSchema(BaseModel):
    """
    技能参数元数据（API 返回格式）
    
    前端通过此信息在弹框中显示参数说明和可点击的示例值
    """
    label: str = Field(..., description="参数中文名称")
    description: str = Field(..., description="参数功能说明")
    examples: List[str] = Field(default_factory=list, description="示例值列表")
    required: bool = Field(True, description="是否必填")


class SkillInfo(BaseModel):
    """技能信息"""
    skill_id: str = Field(..., description="技能 ID")
    name: str = Field(..., description="技能名称")
    description: str = Field(..., description="技能描述")
    required_tools: List[str] = Field(..., description="必需工具列表")
    optional_tools: List[str] = Field(default_factory=list, description="可选工具列表")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    # NOTE: 参数元数据字典，key 为 prompt_template 中的变量名，value 为说明和示例
    param_schemas: Dict[str, SkillParamSchema] = Field(
        default_factory=dict,
        description="参数元数据，key 为变量名，value 为参数说明和示例"
    )


# =============================================================================
# Tool API Schema
# =============================================================================

class ToolInfo(BaseModel):
    """工具信息"""
    name: str = Field(..., description="工具名称")
    description: str = Field(..., description="工具描述")
    parameters: Dict[str, Any] = Field(..., description="参数 Schema")


# =============================================================================
# Agent 流式 API Schema
# =============================================================================

class AgentStreamEventType(str, Enum):
    """Agent 流式事件类型枚举"""
    PLAN_START = "plan_start"           # 开始规划
    PLAN_REASONING = "plan_reasoning"   # 规划推理过程（流式）
    PLAN_COMPLETE = "plan_complete"     # 规划完成
    STEP_START = "step_start"           # 开始执行步骤
    STEP_PROGRESS = "step_progress"     # 步骤执行中
    STEP_COMPLETE = "step_complete"     # 步骤执行完成
    TOOL_START = "tool_start"           # 开始调用工具
    TOOL_COMPLETE = "tool_complete"     # 工具调用完成
    DELEGATE_START = "delegate_start"  # 开始委派子 Agent
    DELEGATE_COMPLETE = "delegate_complete"  # 委派子 Agent 完成
    REFLECTION_START = "reflection_start"  # 开始反思
    REFLECTION_COMPLETE = "reflection_complete"  # 反思完成
    FINAL_ANSWER = "final_answer"      # 最终答案
    ERROR = "error"                    # 执行错误
    COMPLETE = "complete"               # 执行完成


class AgentStreamEvent(BaseModel):
    """
    Agent 流式事件模型
    
    用于实时推送 Agent 执行过程中的各个阶段事件，
    让前端可以逐步展示 Agent 的思考、计划、工具调用等执行轨迹。
    
    事件流向示例：
    1. plan_start -> plan_reasoning(多次) -> plan_complete
    2. step_start -> tool_start -> tool_complete -> step_complete (循环)
    3. reflection_start -> reflection_complete
    4. final_answer
    5. complete
    """
    # 事件类型
    event: AgentStreamEventType = Field(..., description="事件类型")
    # 迭代次数
    iteration: int = Field(0, description="当前迭代次数")
    # 步骤索引（从 1 开始）
    step_index: Optional[int] = Field(None, description="当前步骤索引")
    # 步骤总数
    step_total: Optional[int] = Field(None, description="步骤总数")
    # 事件数据（不同类型事件包含不同数据）
    data: Dict[str, Any] = Field(default_factory=dict, description="事件携带的数据")
    # 错误信息（仅 error 类型事件）
    error: Optional[str] = Field(None, description="错误信息")
    # 时间戳
    timestamp: float = Field(..., description="事件时间戳（毫秒）")

    class Config:
        use_enum_values = True
