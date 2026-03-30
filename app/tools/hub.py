from typing import Dict, List, Optional, Type, Callable, Any
from functools import wraps
import inspect
from pydantic import create_model
from app.tools.base import Tool, ToolSchema

class ToolHub:
    """工具中心，负责工具的注册和管理"""
    
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
    
    def register_tool(self, tool: Tool):
        """
        注册工具实例
        
        Args:
            tool: Tool 实例
        """
        if tool.name in self._tools:
            # 允许覆盖或抛出异常，这里选择覆盖并记录日志（暂无日志）
            pass
        self._tools[tool.name] = tool
    
    def get_tool(self, name: str) -> Optional[Tool]:
        """
        获取工具
        
        Args:
            name: 工具名称
            
        Returns:
            Optional[Tool]: 工具实例，若不存在则返回 None
        """
        return self._tools.get(name)
    
    def list_tools(self) -> List[Tool]:
        """获取所有已注册工具"""
        return list(self._tools.values())
    
    def get_schemas(self) -> List[Dict[str, Any]]:
        """
        获取所有工具的 Schema 列表（用于 LLM function calling）

        返回符合 OpenAI function calling 规范的格式：
        {
            "type": "function",
            "function": {
                "name": "...",
                "description": "...",
                "parameters": {...}
            }
        }
        """
        schemas = []
        for tool in self._tools.values():
            schema = tool.schema.model_dump()
            # 包装为 OpenAI function calling 格式
            schemas.append({
                "type": "function",
                "function": {
                    "name": schema.get("name", ""),
                    "description": schema.get("description", ""),
                    "parameters": schema.get("parameters", {"type": "object", "properties": {}})
                }
            })
        return schemas

    def get_planning_safe_names(self) -> set:
        """
        获取所有 planning_safe=True 的工具名称集合。

        设计原因：
        - Planning 阶段的 LLM tool-calling loop 只应调用只读探查类工具，
          防止副作用工具（如 skill_install、shell_exec、file_write）在规划阶段执行，
          导致 Reflection 看不到执行记录，进而误判并触发多余重规划。
        - 此方法提供一个集合供 PlanningEngine 做二次过滤，不影响 Execution 阶段的完整工具访问。
        - 判断依据是 Tool 基类的 planning_safe 类变量，子类可按需覆盖。
        """
        return {
            name
            for name, tool in self._tools.items()
            if getattr(tool, "planning_safe", True)
        }

def tool(name: str = None, description: str = None):
    """
    工具装饰器，将普通函数转换为 Tool 实例
    
    Args:
        name: 工具名称，默认使用函数名
        description: 工具描述，默认使用函数 docstring
    """
    def decorator(func: Callable) -> Tool:
        tool_name = name or func.__name__
        tool_desc = description or func.__doc__ or "No description provided."
        
        # 简单推断参数 Schema (这里仅作简化实现，完整版需解析 TypeHint)
        # 实际项目中建议使用 Pydantic 的 validate_arguments 或类似的库来生成 Schema
        # 这里为了演示 Task 0.3，我们创建一个包装类
        
        class FunctionTool(Tool):
            def __init__(self):
                self._name = tool_name
                self._description = tool_desc
                # 简化的参数 Schema
                self._parameters = {
                    "type": "object",
                    "properties": {},  # TODO: 使用 inspect 解析参数
                    "required": []
                }
            
            @property
            def name(self) -> str:
                return self._name
            
            @property
            def schema(self) -> ToolSchema:
                return ToolSchema(
                    name=self._name,
                    description=self._description,
                    parameters=self._parameters
                )
            
            async def execute(self, params: Dict[str, Any]) -> Any:
                if inspect.iscoroutinefunction(func):
                    return await func(**params)
                return func(**params)
        
        return FunctionTool()
    return decorator
