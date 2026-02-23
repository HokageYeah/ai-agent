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


class AgentInfo(BaseModel):
    """Agent 信息"""
    agent_id: str = Field(..., description="Agent ID")
    name: str = Field(..., description="Agent 名称")
    description: str = Field(..., description="Agent 描述")
    capabilities: List[str] = Field(..., description="能力列表")
    available_tools: List[str] = Field(..., description="可用工具列表")
    available_skills: List[str] = Field(..., description="可用技能列表")
    child_agents: List[str] = Field(default_factory=list, description="子 Agent 列表")


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


class SkillInfo(BaseModel):
    """技能信息"""
    skill_id: str = Field(..., description="技能 ID")
    name: str = Field(..., description="技能名称")
    description: str = Field(..., description="技能描述")
    required_tools: List[str] = Field(..., description="必需工具列表")
    optional_tools: List[str] = Field(default_factory=list, description="可选工具列表")
    tags: List[str] = Field(default_factory=list, description="标签列表")


# =============================================================================
# Tool API Schema
# =============================================================================

class ToolInfo(BaseModel):
    """工具信息"""
    name: str = Field(..., description="工具名称")
    description: str = Field(..., description="工具描述")
    parameters: Dict[str, Any] = Field(..., description="参数 Schema")
