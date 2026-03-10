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


def register_all_builtin_tools(tool_hub, seed_order_data: bool = True) -> None:
    """
    将所有内置工具注册到 ToolHub 中，并自动初始化订单测试数据。
    
    这是一个便捷函数，供 API 端点等模块在初始化时调用，
    一次性将所有内置工具注册到工具中心，无需逐个手动注册。
    
    Args:
        tool_hub: ToolHub 实例，用于接收工具注册
        seed_order_data: 是否自动向内存数据库注入订单测试数据，默认为 True
        
    使用示例：
        from app.tools.hub import ToolHub
        from app.tools.builtin import register_all_builtin_tools
        
        tool_hub = ToolHub()
        register_all_builtin_tools(tool_hub)
    """
    from loguru import logger
    from colorama import Fore, Style
    print("register_all_builtin_tools")
    # 先创建 DatabaseQueryTool 实例，后续需要对它进行数据注入
    db_tool = DatabaseQueryTool()
    
    # NOTE: 按照工具类别逐一实例化并注册，方便追踪注册状态
    builtin_tools = [
        SearchTool(),
        HTTPRequestTool(),
        PythonExecutorTool(),
        FileReadTool(),
        FileWriteTool(),
        db_tool,        # 复用已创建的实例，确保种子数据注入到同一连接
        CalculatorTool(),
        DateTimeTool(),
    ]
    
    for tool in builtin_tools:
        tool_hub.register_tool(tool)
        logger.debug(f"{Fore.GREEN}已注册内置工具: {tool.name}{Style.RESET_ALL}")
    
    logger.info(
        f"{Fore.GREEN}所有内置工具注册完成，共注册 {len(builtin_tools)} 个工具{Style.RESET_ALL}"
    )
    
    # 向 DatabaseQueryTool 的共享内存数据库注入订单测试数据
    if seed_order_data:
        try:
            from app.db.seed_order_data import seed_database, print_data_summary
            # 步骤1: 建表 + 插入测试数据
            db_tool.seed_data(seed_database)
            # 步骤2: 打印数据摘要供调试
            db_tool.seed_data(print_data_summary)
            # 步骤3: 将真实 Schema（表名+列名+类型）追加到工具描述中
            #         LLM 在规划 SQL 时能看到准确的列名，避免列名猜错导致查询失败
            db_tool.refresh_schema_description()
            logger.info(
                f"{Fore.GREEN}[工具初始化] 订单测试数据已注入内存数据库，"
                f"Schema 已同步到工具描述，Agent 现在可以查询订单 1001-1010{Style.RESET_ALL}"
            )
        except Exception as e:
            logger.error(
                f"{Fore.RED}[工具初始化] 订单测试数据注入失败（不影响其他功能）: {e}{Style.RESET_ALL}"
            )
