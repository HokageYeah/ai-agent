"""
内置工具模块

本模块包含所有内置的工具实现，包括：
- SearchTool: 网络搜索工具
- HTTPRequestTool: HTTP 请求工具
- PythonExecutorTool: Python 代码执行工具
- FileReadTool: 文件读取工具
- FileWriteTool: 文件写入工具
- DatabaseQueryTool: 数据库查询工具
- CalculatorTool: 计算器工具
- DateTimeTool: 日期时间工具

每个工具都继承自 Tool 抽象基类，实现标准化的工具接口。
"""

from app.tools.builtin.search import SearchTool
from app.tools.builtin.http import HTTPRequestTool
from app.tools.builtin.executor import PythonExecutorTool
from app.tools.builtin.file import FileReadTool, FileWriteTool
from app.tools.builtin.database import DatabaseQueryTool
from app.tools.builtin.calculator import CalculatorTool
from app.tools.builtin.datetime import DateTimeTool

# 导出所有内置工具，方便统一注册
__all__ = [
    "SearchTool",
    "HTTPRequestTool", 
    "PythonExecutorTool",
    "FileReadTool",
    "FileWriteTool",
    "DatabaseQueryTool",
    "CalculatorTool",
    "DateTimeTool",
    "register_all_builtin_tools",
]


def register_all_builtin_tools(tool_hub) -> None:
    """
    将所有内置工具注册到 ToolHub 中
    
    这是一个便捷函数，供 API 端点等模块在初始化时调用，
    一次性将所有内置工具注册到工具中心，无需逐个手动注册。
    
    Args:
        tool_hub: ToolHub 实例，用于接收工具注册
        
    使用示例：
        from app.tools.hub import ToolHub
        from app.tools.builtin import register_all_builtin_tools
        
        tool_hub = ToolHub()
        register_all_builtin_tools(tool_hub)
    """
    from loguru import logger
    from colorama import Fore, Style
    
    # NOTE: 按照工具类别逐一实例化并注册，方便追踪注册状态
    builtin_tools = [
        SearchTool(),
        HTTPRequestTool(),
        PythonExecutorTool(),
        FileReadTool(),
        FileWriteTool(),
        DatabaseQueryTool(),
        CalculatorTool(),
        DateTimeTool(),
    ]
    
    for tool in builtin_tools:
        tool_hub.register_tool(tool)
        logger.debug(f"{Fore.GREEN}已注册内置工具: {tool.name}{Style.RESET_ALL}")
    
    logger.info(
        f"{Fore.GREEN}所有内置工具注册完成，共注册 {len(builtin_tools)} 个工具{Style.RESET_ALL}"
    )
