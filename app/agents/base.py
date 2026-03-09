from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field
from enum import Enum
import os


class AgentExample(BaseModel):
    """
    Agent 示例任务模型

    用于前端展示快捷示例标签，帮助用户快速了解 Agent 的使用方式。
    每个 Agent 可以配置多个示例任务，前端从 API 获取后动态渲染。
    """
    label: str = Field(..., description="示例标签（如：示例1：简单查询）")
    content: str = Field(..., description="示例任务内容（点击后填入输入框）")
    style: Optional[str] = Field(None, description="可选样式标识（如：delegate 表示委派类型）")


class AgentConfig(BaseModel):
    """
    Agent 配置模型
    
    默认模型配置从环境变量 DEFAULT_MODEL 读取
    """
    planning_model: str = Field(
        default_factory=lambda: os.getenv("DEFAULT_MODEL", "gpt-3.5-turbo"),
        description="规划使用的模型"
    )
    execution_model: str = Field(
        default_factory=lambda: os.getenv("DEFAULT_MODEL", "gpt-3.5-turbo"),
        description="执行使用的模型"
    )
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

    # 示例任务列表（供前端展示快捷示例标签）
    examples: List[AgentExample] = Field(
        default_factory=list,
        description="示例任务列表，用于前端展示快捷示例标签"
    )

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
