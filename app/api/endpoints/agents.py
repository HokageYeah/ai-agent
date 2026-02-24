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
from app.agents.child_agent_manager import ChildAgentManager
from app.llm_hub.inference import InferenceEngine
from app.tools.hub import ToolHub
from app.skills.manager import SkillManager

# 创建路由器
router = APIRouter()

# 全局服务实例
_agent_registry: AgentRegistry = None
_agent_executor: LangGraphAgentExecutor = None
_child_agent_manager: ChildAgentManager = None


def get_agent_registry() -> AgentRegistry:
    """
    获取 AgentRegistry 实例（依赖注入）
    
    Returns:
        AgentRegistry: Agent 注册表实例
    """
    global _agent_registry
    if _agent_registry is None:
        logger.info(f"{Fore.BLUE}初始化 AgentRegistry...{Style.RESET_ALL}")
        _agent_registry = AgentRegistry()
        
        # 注册所有内置 Agent
        from app.agents.library.customer_service import register_customer_service_agents
        register_customer_service_agents(_agent_registry)
        
        logger.info(f"{Fore.GREEN}AgentRegistry 初始化完成{Style.RESET_ALL}")
    
    return _agent_registry


def get_agent_executor() -> LangGraphAgentExecutor:
    """
    获取 LangGraphAgentExecutor 实例（依赖注入）
    
    同时初始化 ChildAgentManager，使父 Agent 能够将任务委派给子 Agent。
    
    Returns:
        LangGraphAgentExecutor: Agent 执行器实例
    """
    global _agent_executor, _child_agent_manager
    if _agent_executor is None:
        logger.info(f"{Fore.BLUE}初始化 LangGraphAgentExecutor...{Style.RESET_ALL}")
        
        # NOTE: InferenceEngine 需要 provider 和 model_registry 两个必填参数
        # 参照 chat.py 的做法，先创建 OpenAIProvider 和 ModelRegistry，再传入 InferenceEngine
        from app.llm_hub.providers.openai import OpenAIProvider
        from app.llm_hub.registry import ModelRegistry
        from app.core.config import settings
        
        # 创建默认 LLM Provider（使用 OpenAI 兼容接口）
        provider = OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL
        )
        logger.info(f"{Fore.CYAN}已创建 OpenAIProvider（base_url={settings.OPENAI_BASE_URL}）{Style.RESET_ALL}")
        
        # 创建模型注册中心
        model_registry = ModelRegistry()
        logger.info(f"{Fore.CYAN}已创建 ModelRegistry{Style.RESET_ALL}")
        
        # 创建推理引擎（需要 provider 和 model_registry 两个必填参数）
        inference_engine = InferenceEngine(
            provider=provider,
            model_registry=model_registry
        )
        logger.info(f"{Fore.CYAN}已创建 InferenceEngine{Style.RESET_ALL}")
        
        tool_hub = ToolHub()
        skill_manager = SkillManager()
        
        # 注册所有内置工具和技能
        from app.tools.builtin import register_all_builtin_tools
        from app.skills.library import register_all_builtin_skills
        register_all_builtin_tools(tool_hub)
        register_all_builtin_skills(skill_manager)
        
        # 获取 Agent 注册表（确保已初始化）
        agent_registry = get_agent_registry()
        
        # 创建子 Agent 管理器，让父 Agent 能把任务委派给子 Agent
        _child_agent_manager = ChildAgentManager(
            agent_registry=agent_registry,
            llm_hub=inference_engine,
            tool_hub=tool_hub,
            skill_manager=skill_manager
        )
        logger.info(f"{Fore.CYAN}已创建 ChildAgentManager，支持多层 Agent 委派{Style.RESET_ALL}")
        
        # 创建执行器，传入子 Agent 管理器
        _agent_executor = LangGraphAgentExecutor(
            llm_hub=inference_engine,
            tool_hub=tool_hub,
            skill_manager=skill_manager,
            child_agent_manager=_child_agent_manager
        )
        
        logger.info(f"{Fore.GREEN}LangGraphAgentExecutor 初始化完成（含 ChildAgentManager）{Style.RESET_ALL}")
    
    return _agent_executor


@router.post("/agents/{agent_id}/execute")
async def execute_agent(
    agent_id: str,
    request: AgentExecuteRequest,
    agent_registry: AgentRegistry = Depends(get_agent_registry),
    agent_executor: LangGraphAgentExecutor = Depends(get_agent_executor)
) -> ApiResponseData:
    """
    执行 Agent
    
    Args:
        agent_id: Agent ID
        request: 执行请求
        agent_registry: Agent 注册表
        agent_executor: Agent 执行器
        
    Returns:
        ApiResponseData: 统一响应格式
    """
    logger.info(f"{Fore.CYAN}接收到 Agent 执行请求 - Agent ID: {agent_id}{Style.RESET_ALL}")
    logger.info(f"{Fore.CYAN}任务: {request.task}{Style.RESET_ALL}")
    
    try:
        # 获取 Agent
        agent = agent_registry.get_agent(agent_id)
        if not agent:
            logger.error(f"{Fore.RED}Agent 不存在: {agent_id}{Style.RESET_ALL}")
            raise HTTPException(status_code=404, detail=f"Agent 不存在: {agent_id}")
        
        # 执行 Agent
        result = await agent_executor.execute(
            agent=agent,
            task=request.task,
            conversation_history=request.conversation_history
        )
        
        logger.info(f"{Fore.GREEN}Agent 执行成功{Style.RESET_ALL}")
        
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
        logger.error(f"{Fore.RED}Agent 执行失败: {e}{Style.RESET_ALL}")
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
