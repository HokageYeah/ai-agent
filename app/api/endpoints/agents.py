"""
Agent API Endpoints (Agent 接口)
================================

本模块提供 Agent 相关的 REST API 端点。

功能特点：
1. POST /agents/{agent_id}/execute - 执行 Agent（非流式，返回完整结果）
2. POST /agents/{agent_id}/execute/stream - 流式执行 Agent（实时推送执行轨迹）
3. GET /agents - 列出所有 Agent
4. GET /agents/{agent_id} - 获取 Agent 详情

作者: AI Agent Team
创建时间: 2026-02-17
更新时间: 2026-02-27（添加流式执行端点）
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from typing import List, AsyncIterator
from loguru import logger
from colorama import Fore, Style
import json

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
                    "conversation_id": request.conversation_id,
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
            
            # 使用依赖注入获取全局 Agent 执行器（内部已包含完整的 llm_hub/tool_hub 等）
            from app.utils.dependencies import get_agent_executor
            agent_executor = get_agent_executor()
            if request.conversation_id:
                logger.info(
                    f"{Fore.CYAN}[API路由] 检测到参数 conversation_id='{request.conversation_id}'，"
                    f"将激活会话级上下文记忆链{Style.RESET_ALL}"
                )
            else:
                logger.debug(
                    f"{Fore.YELLOW}[API路由] 未提供 conversation_id，本次执行将独立进行"
                    f"{Style.RESET_ALL}"
                )

            # 阻塞执行 Agent
            result = await agent_executor.execute(
                agent=agent,
                task=request.task,
                conversation_id=request.conversation_id,
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


@router.post("/agents/{agent_id}/execute/stream")
async def execute_agent_stream(
    agent_id: str,
    request: AgentExecuteRequest,
    agent_registry: AgentRegistry = Depends(get_agent_registry),
    agent_executor: LangGraphAgentExecutor = Depends(get_agent_executor)
):
    """
    流式执行 Agent（Server-Sent Events）
    
    这是一个流式端点，通过 Server-Sent Events (SSE) 实时推送 Agent 执行过程中的各个阶段事件，
    让前端可以逐步展示 Agent 的思考、计划、工具调用等执行轨迹。

    消息流向：
      前端 HTTP 请求
        ↓
      LangGraphAgentExecutor.execute_stream()
        ↓
      逐个 yield 执行事件（SSE）
        ↓
      前端 EventSource 接收并展示

    事件类型：
      - plan_start: 开始规划
      - plan_reasoning: 规划推理过程
      - plan_complete: 规划完成
      - step_start: 开始执行步骤
      - step_progress: 步骤执行中
      - step_complete: 步骤执行完成
      - tool_start: 开始调用工具
      - tool_complete: 工具调用完成
      - delegate_start: 开始委派子 Agent
      - delegate_complete: 委派子 Agent 完成
      - reflection_start: 开始反思
      - reflection_complete: 反思完成
      - final_answer: 最终答案
      - error: 执行错误
      - complete: 执行完成

    Args:
        agent_id: Agent ID
        request: 执行请求体
        agent_registry: Agent 注册表（依赖注入）
        agent_executor: Agent 执行器（依赖注入）

    Returns:
        StreamingResponse: Server-Sent Events 流
    """
    logger.info(
        f"{Fore.CYAN}【Agent流式接口】接收到 Agent 流式执行请求 — "
        f"Agent ID: {agent_id}{Style.RESET_ALL}"
    )
    logger.info(f"{Fore.CYAN}【Agent流式接口】任务: {request.task[:100]}{Style.RESET_ALL}")

    # 验证 Agent 是否存在
    agent = agent_registry.get_agent(agent_id)
    if not agent:
        logger.error(f"{Fore.RED}【Agent流式接口】Agent 不存在: {agent_id}{Style.RESET_ALL}")
        raise HTTPException(status_code=404, detail=f"Agent 不存在: {agent_id}")

    async def generate_stream() -> AsyncIterator[str]:
        """
        内部生成器：从 AgentExecutor 获取流式事件
        
        使用 SSE (Server-Sent Events) 格式发送事件：
        data: {json}
        """
        # 使用依赖注入获取全局流式 Agent 执行器
        from app.utils.dependencies import get_agent_executor
        agent_executor = get_agent_executor()
        
        if request.conversation_id:
            logger.info(
                f"{Fore.CYAN}[API路由] (流式运行) 检测到 conversation_id='{request.conversation_id}'，"
                f"将激活会话级任务摘要注入机制{Style.RESET_ALL}"
            )
        else:
            logger.debug(
                f"{Fore.YELLOW}[API路由] (流式运行) 无 conversation_id 参数，本次执行保持完全隔离"
                f"{Style.RESET_ALL}"
            )

        # 使用 execute_stream 方法获取异步生成器
        try:
            async for event in agent_executor.execute_stream(
                agent=agent,
                task=request.task,
                conversation_id=request.conversation_id,
                conversation_history=request.conversation_history
            ):
                # 将事件序列化为 JSON 并用 SSE 格式发送
                event_json = json.dumps(event, ensure_ascii=False)
                yield f"data: {event_json}\n\n"
                
                # 记录日志
                event_type = event.get("event", "unknown")
                iteration = event.get("iteration", 0)
                logger.debug(
                    f"{Fore.BLUE}[Agent流式接口] 发送事件: {event_type}, "
                    f"迭代: {iteration}{Style.RESET_ALL}"
                )

            logger.info(
                f"{Fore.GREEN}【Agent流式接口】Agent 流式执行完成{Style.RESET_ALL}"
            )

        except Exception as e:
            logger.error(
                f"{Fore.RED}【Agent流式接口】Agent 流式执行失败: {e}{Style.RESET_ALL}"
            )
            # 发送错误事件
            error_event = {
                "event": "error",
                "error": str(e),
                "timestamp": __import__("time").time() * 1000
            }
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # 禁用 Nginx 缓冲
        }
    )


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
                child_agents=agent.child_agents,
                examples=[ex.model_dump() for ex in agent.examples]
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


# ─────────────────────────────────────────────────────────────────────────────
# 用户确认接口
# ─────────────────────────────────────────────────────────────────────────────

from pydantic import BaseModel


class ConfirmRequest(BaseModel):
    """用户确认请求体"""
    action: str  # "confirm" 或 "reject"


@router.post("/agents/confirm/{confirm_id}")
async def confirm_agent_action(
    confirm_id: str,
    request: ConfirmRequest,
    agent_executor: LangGraphAgentExecutor = Depends(get_agent_executor)
) -> ApiResponseData:
    """
    用户确认/拒绝 Agent 即将执行的操作。

    当 Agent 计划执行需要用户确认的操作（如 file_write）时，
    前端会展示确认卡片，用户点击「确认」或「取消」后调用本接口。

    本接口通过 confirm_id 找到进程内挂起的 asyncio.Event，
    写入用户决定（confirm/reject）并 set event，唤醒挂起的执行节点继续流程。

    Args:
        confirm_id: 唯一确认 ID（由 user_confirm_required 事件携带）
        request: 包含 action 字段（"confirm" 或 "reject"）
        agent_executor: Agent 执行器（依赖注入）

    Returns:
        ApiResponseData: 统一响应格式
    """
    logger.info(
        f"{Fore.CYAN}【确认接口】收到用户确认请求 — "
        f"confirm_id: {confirm_id}, action: {request.action}{Style.RESET_ALL}"
    )

    # 校验 action 合法性
    if request.action not in ("confirm", "reject"):
        raise HTTPException(
            status_code=400,
            detail=f"无效的 action 值: {request.action}，必须为 'confirm' 或 'reject'"
        )

    # 在执行器的 _pending_confirmations 中查找挂起的确认事件
    pending = agent_executor._pending_confirmations.get(confirm_id)
    if not pending:
        logger.warning(
            f"{Fore.YELLOW}【确认接口】confirm_id 不存在或已超时: {confirm_id}{Style.RESET_ALL}"
        )
        raise HTTPException(
            status_code=404,
            detail=f"确认 ID 不存在或已超时: {confirm_id}"
        )

    # 写入用户决定并唤醒挂起的执行节点
    pending["action"] = request.action
    pending["event"].set()

    action_text = "已确认执行" if request.action == "confirm" else "已拒绝执行"
    logger.info(
        f"{Fore.GREEN}【确认接口】{action_text}，"
        f"confirm_id={confirm_id}{Style.RESET_ALL}"
    )

    return ApiResponseData(
        platform=PlatformEnum.WX_PUBLIC,
        api=f"/agents/confirm/{confirm_id}",
        data={"confirm_id": confirm_id, "action": request.action, "message": action_text},
        ret=["success"],
        v=1
    )


