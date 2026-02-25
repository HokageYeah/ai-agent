"""
Agent API Endpoints (Agent 接口)
================================

本模块提供 Agent 相关的 REST API 端点。

功能特点：
1. POST /agents/{agent_id}/execute - 执行 Agent
2. GET /agents - 列出所有 Agent
3. GET /agents/{agent_id} - 获取 Agent 详情

作者: AI Agent Team
创建时间: 2026-02-17
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import List
from loguru import logger
from colorama import Fore, Style

from app.schemas.agent_data import (
    AgentExecuteRequest, AgentExecuteResponse,
    AgentInfo, AgentDetail
)
from app.schemas.common_data import ApiResponseData, PlatformEnum
from app.agents.registry import AgentRegistry
from app.agents.langgraph_executor import LangGraphAgentExecutor
from app.utils.dependencies import get_agent_registry, get_agent_executor

# 创建路由器
router = APIRouter()


@router.post("/agents/{agent_id}/execute")
async def execute_agent(
    agent_id: str,
    request: AgentExecuteRequest,
    agent_registry: AgentRegistry = Depends(get_agent_registry),
    agent_executor: LangGraphAgentExecutor = Depends(get_agent_executor)
) -> ApiResponseData:
    """
    执行 Agent（经由 Channel Layer 标准化处理）

    消息流向（遵循分层架构）：
      前端 HTTP 请求
        ↓
      RESTAPIAdapter（渠道层：标准化消息格式）
        ↓
      ChannelManager.route_message(service_type="agent")
        ↓
      LangGraphAgentExecutor.execute()（编排层）
        ↓
      PlanningEngine → ExecutionEngine → ReflectionEngine
        ↓
      响应返回

    Args:
        agent_id: Agent ID
        request: 执行请求体
        agent_registry: Agent 注册表（依赖注入）
        agent_executor: Agent 执行器（依赖注入）

    Returns:
        ApiResponseData: 统一响应格式
    """
    logger.info(
        f"{Fore.CYAN}【Agent接口】接收到 Agent 执行请求 — "
        f"Agent ID: {agent_id}{Style.RESET_ALL}"
    )
    logger.info(f"{Fore.CYAN}【Agent接口】任务: {request.task[:100]}{Style.RESET_ALL}")

    try:
        # 验证 Agent 是否存在（在进入渠道之前做前置校验，避免无效消息进入）
        agent = agent_registry.get_agent(agent_id)
        if not agent:
            logger.error(f"{Fore.RED}【Agent接口】Agent 不存在: {agent_id}{Style.RESET_ALL}")
            raise HTTPException(status_code=404, detail=f"Agent 不存在: {agent_id}")

        # ── 通过 Channel Layer 路由（标准架构分层流程）────────────────
        from app.channels.manager import get_channel_manager

        channel_manager = get_channel_manager()

        if channel_manager.get_adapter("rest_api") is not None:
            logger.info(
                f"{Fore.BLUE}【Agent接口】通过 Channel Layer 路由 (渠道: rest_api){Style.RESET_ALL}"
            )

            # 构建渠道层原始消息格式
            # content = 任务描述，metadata 携带 Agent 执行所需的额外参数
            raw_message = {
                "user_id": agent_id,
                "content": request.task,           # 任务内容作为消息主体
                "metadata": {
                    "service_type": "agent",        # 路由目标：Agent 执行器
                    "agent_id": agent_id,
                    "conversation_history": request.conversation_history or [],
                    "config": request.config or {},
                }
            }

            result = await channel_manager.route_message("rest_api", raw_message)

        else:
            # ── 降级模式：直接调用 AgentExecutor（兼容测试/独立部署）────
            logger.info(
                f"{Fore.YELLOW}【Agent接口】Channel Layer 未就绪，"
                f"降级为直接调用 AgentExecutor{Style.RESET_ALL}"
            )
            result = await agent_executor.execute(
                agent=agent,
                task=request.task,
                conversation_history=request.conversation_history
            )

        logger.info(
            f"{Fore.GREEN}【Agent接口】Agent 执行成功, "
            f"success={result.get('success')}{Style.RESET_ALL}"
        )

        # 构建响应
        response = AgentExecuteResponse(
            agent_id=agent.agent_id,
            agent_name=agent.name,
            task=request.task,
            result=result.get("result", {}),
            iterations=result.get("iterations", 0),
            success=result.get("success", False),
            messages=result.get("messages", [])
        )

        return ApiResponseData(
            platform=PlatformEnum.WX_PUBLIC,
            api=f"/agents/{agent_id}/execute",
            data=response.model_dump(),
            ret=["success"],
            v=1
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"{Fore.RED}【Agent接口】Agent 执行失败: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail=f"Agent 执行失败: {str(e)}")


@router.get("/agents")
async def list_agents(
    agent_registry: AgentRegistry = Depends(get_agent_registry)
) -> ApiResponseData:
    """
    列出所有 Agent
    
    Args:
        agent_registry: Agent 注册表
        
    Returns:
        ApiResponseData: 统一响应格式
    """
    logger.info(f"{Fore.CYAN}列出所有 Agent{Style.RESET_ALL}")
    
    try:
        # 获取所有 Agent
        agents = agent_registry.list_agents()
        
        # 构建响应
        agents_info = [
            AgentInfo(
                agent_id=agent.agent_id,
                name=agent.name,
                description=agent.description,
                capabilities=agent.capabilities,
                available_tools=agent.available_tools,
                available_skills=agent.available_skills,
                child_agents=agent.child_agents
            )
            for agent in agents
        ]
        
        logger.info(f"{Fore.GREEN}成功列出 {len(agents_info)} 个 Agent{Style.RESET_ALL}")
        
        return ApiResponseData(
            platform=PlatformEnum.WX_PUBLIC,
            api="/agents",
            data=[info.model_dump() for info in agents_info],
            ret=["success"],
            v=1
        )
        
    except Exception as e:
        logger.error(f"{Fore.RED}列出 Agent 失败: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail=f"列出 Agent 失败: {str(e)}")


@router.get("/agents/{agent_id}")
async def get_agent(
    agent_id: str,
    agent_registry: AgentRegistry = Depends(get_agent_registry)
) -> ApiResponseData:
    """
    获取 Agent 详情
    
    Args:
        agent_id: Agent ID
        agent_registry: Agent 注册表
        
    Returns:
        ApiResponseData: 统一响应格式
    """
    logger.info(f"{Fore.CYAN}获取 Agent 详情 - Agent ID: {agent_id}{Style.RESET_ALL}")
    
    try:
        # 获取 Agent
        agent = agent_registry.get_agent(agent_id)
        if not agent:
            logger.error(f"{Fore.RED}Agent 不存在: {agent_id}{Style.RESET_ALL}")
            raise HTTPException(status_code=404, detail=f"Agent 不存在: {agent_id}")
        
        # 构建响应
        detail = AgentDetail(
            agent_id=agent.agent_id,
            name=agent.name,
            description=agent.description,
            role=agent.role,
            capabilities=agent.capabilities,
            available_tools=agent.available_tools,
            available_skills=agent.available_skills,
            child_agents=agent.child_agents,
            agent_config=agent.agent_config.model_dump()
        )
        
        logger.info(f"{Fore.GREEN}成功获取 Agent 详情{Style.RESET_ALL}")
        
        return ApiResponseData(
            platform=PlatformEnum.WX_PUBLIC,
            api=f"/agents/{agent_id}",
            data=detail.model_dump(),
            ret=["success"],
            v=1
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"{Fore.RED}获取 Agent 详情失败: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail=f"获取 Agent 详情失败: {str(e)}")
