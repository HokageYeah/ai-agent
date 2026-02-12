from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field, ConfigDict
from sys import stdout
from loguru import logger
from colorama import Fore, Style

# 配置 Loguru
logger.remove()
logger.add(stdout, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>")

class MemoryStrategy(BaseModel):
    """
    记忆策略配置
    
    决定技能执行时如何使用上下文记忆
    """
    include_short_term: bool = Field(True, description="是否包含短期对话记忆")
    # 可以扩展长期记忆等其他策略

class Skill(BaseModel):
    """
    技能定义数据模型
    
    技能是预定义的能力单元，包含 Prompt 模板和工具依赖
    """
    skill_id: str = Field(..., description="技能唯一标识")
    name: str = Field(..., description="技能名称")
    description: str = Field(..., description="技能描述")
    prompt_template: str = Field(..., description="Prompt 模板，支持 {variable} 格式插值")
    required_tools: List[str] = Field(default_factory=list, description="依赖的工具名称列表")
    optional_tools: List[str] = Field(default_factory=list, description="可选的工具名称列表")
    memory_strategy: MemoryStrategy = Field(default_factory=lambda: MemoryStrategy(), description="记忆策略")
    tags: List[str] = Field(default_factory=list, description="技能标签")
    examples: List[Dict[str, Any]] = Field(default_factory=list, description="Few-shot 示例")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "skill_id": "data_analysis",
                "name": "Data Analysis",
                "description": "Analyze datasets and provide insights.",
                "prompt_template": "Analyze the following data: {data}",
                "required_tools": ["python_executor"]
            }
        }
    )
