"""
Tools API Endpoints (工具接口)
================================

本模块提供工具相关的 REST API 端点。

功能特点：
1. GET /tools - 列出所有工具

作者: AI Agent Team
创建时间: 2026-02-17
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import List
from loguru import logger
from colorama import Fore, Style

from app.schemas.agent_data import ToolInfo
from app.schemas.common_data import ApiResponseData, PlatformEnum
from app.tools.hub import ToolHub

# 创建路由器
router = APIRouter()

# 全局服务实例
_tool_hub: ToolHub = None


def get_tool_hub() -> ToolHub:
    """
    获取 ToolHub 实例（依赖注入）
    
    Returns:
        ToolHub: 工具中心实例
    """
    global _tool_hub
    if _tool_hub is None:
        logger.info(f"{Fore.BLUE}初始化 ToolHub...{Style.RESET_ALL}")
        _tool_hub = ToolHub()
        
        # 注册所有内置工具
        from app.tools.builtin import register_all_builtin_tools
        register_all_builtin_tools(_tool_hub)
        
        logger.info(f"{Fore.GREEN}ToolHub 初始化完成{Style.RESET_ALL}")
    
    return _tool_hub


@router.get("/tools")
async def list_tools(
    tool_hub: ToolHub = Depends(get_tool_hub)
) -> ApiResponseData:
    """
    列出所有工具
    
    Args:
        tool_hub: 工具中心
        
    Returns:
        ApiResponseData: 统一响应格式
    """
    logger.info(f"{Fore.CYAN}列出所有工具{Style.RESET_ALL}")
    
    try:
        # 获取所有工具
        tools = tool_hub.list_tools()
        
        # 构建响应
        tools_info = [
            ToolInfo(
                name=tool.name,
                description=tool.schema.description,
                parameters=tool.schema.parameters
            )
            for tool in tools
        ]
        
        logger.info(f"{Fore.GREEN}成功列出 {len(tools_info)} 个工具{Style.RESET_ALL}")
        
        return ApiResponseData(
            platform=PlatformEnum.WX_PUBLIC,
            api="/tools",
            data=[info.model_dump() for info in tools_info],
            ret=["success"],
            v=1
        )
        
    except Exception as e:
        logger.error(f"{Fore.RED}列出工具失败: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail=f"列出工具失败: {str(e)}")
