from abc import ABC, abstractmethod
from typing import Dict, Any, Type
from pydantic import BaseModel, Field

class ToolSchema(BaseModel):
    """工具 Schema 定义"""
    name: str = Field(..., description="工具名称")
    description: str = Field(..., description="工具描述")
    parameters: Dict[str, Any] = Field(..., description="参数 Schema (JSON Schema)")

class Tool(ABC):
    """工具抽象基类"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称"""
        pass
    
    @property
    @abstractmethod
    def schema(self) -> ToolSchema:
        """获取工具 Schema"""
        pass
    
    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> Any:
        """
        执行工具
        
        Args:
            params: 工具参数字典
            
        Returns:
            Any: 执行结果
        """
        pass
