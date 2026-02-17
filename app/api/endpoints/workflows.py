"""
Workflow API Endpoints (工作流接口)
================================

本模块提供工作流相关的 REST API 端点。

功能特点：
1. POST /workflows/{workflow_id}/execute - 执行工作流
2. GET /workflows - 列出所有工作流

作者: AI Agent Team
创建时间: 2026-02-17
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict
from loguru import logger
from colorama import Fore, Style

from app.schemas.agent_data import (
    WorkflowExecuteRequest, WorkflowExecuteResponse,
    WorkflowInfo
)
from app.schemas.common_data import ApiResponseData, PlatformEnum
from app.workflows.engine import WorkflowEngine
from app.workflows.nodes import Workflow

# 创建路由器
router = APIRouter()

# 全局服务实例
_workflow_engine: WorkflowEngine = None
_workflows: Dict[str, Workflow] = {}


def get_workflow_engine() -> WorkflowEngine:
    """
    获取 WorkflowEngine 实例（依赖注入）
    
    Returns:
        WorkflowEngine: 工作流引擎实例
    """
    global _workflow_engine
    if _workflow_engine is None:
        logger.info(f"{Fore.BLUE}初始化 WorkflowEngine...{Style.RESET_ALL}")
        _workflow_engine = WorkflowEngine()
        logger.info(f"{Fore.GREEN}WorkflowEngine 初始化完成{Style.RESET_ALL}")
    
    return _workflow_engine


def get_workflows() -> Dict[str, Workflow]:
    """
    获取所有工作流（依赖注入）
    
    Returns:
        Dict[str, Workflow]: 工作流字典
    """
    global _workflows
    if not _workflows:
        logger.info(f"{Fore.BLUE}加载工作流定义...{Style.RESET_ALL}")
        
        # 注册所有内置工作流
        from app.workflows.templates.intent_routing import INTENT_ROUTING_WORKFLOW
        _workflows[INTENT_ROUTING_WORKFLOW.workflow_id] = INTENT_ROUTING_WORKFLOW
        
        logger.info(f"{Fore.GREEN}工作流定义加载完成，共 {len(_workflows)} 个{Style.RESET_ALL}")
    
    return _workflows


@router.post("/workflows/{workflow_id}/execute")
async def execute_workflow(
    workflow_id: str,
    request: WorkflowExecuteRequest,
    workflow_engine: WorkflowEngine = Depends(get_workflow_engine),
    workflows: Dict[str, Workflow] = Depends(get_workflows)
) -> ApiResponseData:
    """
    执行工作流
    
    Args:
        workflow_id: 工作流 ID
        request: 执行请求
        workflow_engine: 工作流引擎
        workflows: 工作流字典
        
    Returns:
        ApiResponseData: 统一响应格式
    """
    logger.info(f"{Fore.CYAN}接收到工作流执行请求 - Workflow ID: {workflow_id}{Style.RESET_ALL}")
    
    try:
        # 获取工作流定义
        workflow = workflows.get(workflow_id)
        if not workflow:
            logger.error(f"{Fore.RED}工作流不存在: {workflow_id}{Style.RESET_ALL}")
            raise HTTPException(status_code=404, detail=f"工作流不存在: {workflow_id}")
        
        # 执行工作流
        result = await workflow_engine.execute(
            workflow=workflow,
            initial_input=request.input_data
        )
        
        logger.info(f"{Fore.GREEN}工作流执行成功{Style.RESET_ALL}")
        
        # 构建响应
        response = WorkflowExecuteResponse(
            workflow_id=workflow.workflow_id,
            workflow_name=workflow.name,
            result=result,
            success=True
        )
        
        return ApiResponseData(
            platform=PlatformEnum.WX_PUBLIC,
            api=f"/workflows/{workflow_id}/execute",
            data=response.model_dump(),
            ret=["success"],
            v=1
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"{Fore.RED}工作流执行失败: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail=f"工作流执行失败: {str(e)}")


@router.get("/workflows")
async def list_workflows(
    workflows: Dict[str, Workflow] = Depends(get_workflows)
) -> ApiResponseData:
    """
    列出所有工作流
    
    Args:
        workflows: 工作流字典
        
    Returns:
        ApiResponseData: 统一响应格式
    """
    logger.info(f"{Fore.CYAN}列出所有工作流{Style.RESET_ALL}")
    
    try:
        # 构建响应
        workflows_info = [
            WorkflowInfo(
                workflow_id=workflow.workflow_id,
                name=workflow.name,
                description=workflow.description,
                node_count=len(workflow.nodes),
                entry_node=workflow.entry_node,
                exit_nodes=workflow.exit_nodes
            )
            for workflow in workflows.values()
        ]
        
        logger.info(f"{Fore.GREEN}成功列出 {len(workflows_info)} 个工作流{Style.RESET_ALL}")
        
        return ApiResponseData(
            platform=PlatformEnum.WX_PUBLIC,
            api="/workflows",
            data=[info.model_dump() for info in workflows_info],
            ret=["success"],
            v=1
        )
        
    except Exception as e:
        logger.error(f"{Fore.RED}列出工作流失败: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail=f"列出工作流失败: {str(e)}")
