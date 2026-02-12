"""
工具系统模块

本模块提供 AI Agent 的工具调用能力，包括：
- 工具基类（Tool, ToolSchema）
- 工具中心（ToolHub）
- 内置工具集（Builtin Tools）

内置工具：
- search: 网络搜索工具
- http_request: HTTP 请求工具
- python_executor: Python 代码执行工具
- file_read: 文件读取工具
- file_write: 文件写入工具
- database_query: 数据库查询工具
- calculator: 计算器工具
- datetime: 日期时间工具

使用示例：
    from app.tools import ToolHub, SearchTool, HTTPRequestTool
    
    # 创建工具中心
    hub = ToolHub()
    
    # 注册工具
    hub.register_tool(SearchTool())
    hub.register_tool(HTTPRequestTool())
    
    # 获取工具
    search_tool = hub.get_tool("search")
    
    # 执行工具
    result = await search_tool.execute({"query": "Python"})
"""

from app.tools.base import Tool, ToolSchema
from app.tools.hub import ToolHub, tool
from app.tools.builtin import (
    SearchTool,
    HTTPRequestTool,
    PythonExecutorTool,
    FileReadTool,
    FileWriteTool,
    DatabaseQueryTool,
    CalculatorTool,
    DateTimeTool
)

__all__ = [
    # 基类
    "Tool",
    "ToolSchema",
    
    # 工具中心
    "ToolHub",
    "tool",
    
    # 内置工具
    "SearchTool",
    "HTTPRequestTool",
    "PythonExecutorTool",
    "FileReadTool",
    "FileWriteTool",
    "DatabaseQueryTool",
    "CalculatorTool",
    "DateTimeTool",
]
