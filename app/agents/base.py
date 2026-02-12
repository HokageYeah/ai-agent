from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field
from enum import Enum

class AgentConfig(BaseModel):
    """
    Agent 配置模型
    """
    planning_model: str = Field("gpt-4", description="规划使用的模型")
    execution_model: str = Field("gpt-3.5-turbo", description="执行使用的模型")
    max_iterations: int = Field(10, description="最大反思迭代次数")
    timeout_seconds: int = Field(60, description="执行超时时间")

class Agent(BaseModel):
    """
    Agent 数据模型
    
    定义智能体的属性、能力和资源
    """
    agent_id: str = Field(..., description="Agent 唯一标识")
    name: str = Field(..., description="Agent 名称")
    description: str = Field(..., description="Agent 描述")
    role: str = Field(..., description="Agent 角色定义 (System Prompt)")
    capabilities: List[str] = Field(default_factory=list, description="能力标签列表")
    
    # 资源依赖
    available_tools: List[str] = Field(default_factory=list, description="可用工具 ID 列表")
    available_skills: List[str] = Field(default_factory=list, description="可用技能 ID 列表")
    child_agents: List[str] = Field(default_factory=list, description="子 Agent ID 列表")
    
    # 配置
    agent_config: AgentConfig = Field(default_factory=lambda: AgentConfig(), description="模型配置")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "agent_id": "customer_service",
                "name": "Customer Service Agent",
                "description": "Handles customer queries.",
                "role": "You are a helpful customer service assistant.",
                "capabilities": ["chat", "search"],
                "available_tools": ["search_tool"],
                "available_skills": ["sentiment_analysis"]
            }
        }
    }
