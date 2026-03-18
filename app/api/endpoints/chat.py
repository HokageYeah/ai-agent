"""
Chat API Endpoints (对话接口)
================================

本模块提供对话相关的 REST API 端点。

消息流向（遵循分层架构）：
    前端 HTTP 请求
      ↓
    RESTAPIAdapter（渠道层：标准化消息格式）
      ↓
    ChannelManager.route_message()（路由分发）
      ↓
    ChatService.chat()（应用层：处理对话业务逻辑）
      ↓
    InferenceEngine（LLM Hub：统一推理）
      ↓
    响应返回

端点列表：
  1. POST /chat         - 普通对话接口（经由 Channel Layer）
  2. POST /chat/stream  - 流式对话接口（直接调用 ChatService，流式需要特殊处理）
  3. DELETE /chat/{id}  - 清空对话历史

作者: AI Agent Team
创建时间: 2026-02-17
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from typing import AsyncIterator
from loguru import logger
from colorama import Fore, Style

from app.core.config import get_default_model
from app.schemas.agent_data import ChatRequest, ChatResponse
from app.schemas.common_data import ApiResponseData, PlatformEnum
from app.services.chat_service import ChatService
from app.utils.dependencies import get_chat_service

# 创建路由器
router = APIRouter()


@router.post("/chat")
async def chat(
    request: ChatRequest,
    chat_service: ChatService = Depends(get_chat_service)
) -> ApiResponseData:
    """
    普通对话接口（经由 Channel Layer 标准化处理）

    请求流程：
      1. 将 ChatRequest 封装为 REST API 渠道的原始消息格式（dict）
      2. 通过 ChannelManager.route_message() 进入渠道层
      3. 渠道层标准化消息后路由到 ChatService
      4. 返回统一响应格式

    Args:
        request: 对话请求体
        chat_service: 对话服务实例（FastAPI 依赖注入）

    Returns:
        ApiResponseData: 统一响应格式
    """
    logger.info(
        f"{Fore.CYAN}【对话接口】接收到对话请求 — "
        f"会话ID: {request.conversation_id}{Style.RESET_ALL}"
    )
    logger.debug(f"{Fore.CYAN}【对话接口】用户消息: {request.message[:100]}{Style.RESET_ALL}")

    try:
        # ── 通过 Channel Layer 路由（标准架构分层流程）────────────────
        from app.channels.manager import get_channel_manager

        channel_manager = get_channel_manager()

        # NOTE: 检查 ChannelManager 是否已有 rest_api 渠道适配器
        # 如果服务尚未完全启动（如单元测试环境），降级到直接调用 ChatService
        if channel_manager.get_adapter("rest_api") is not None:
            logger.info(
                f"{Fore.BLUE}【对话接口】通过 Channel Layer 路由 (渠道: rest_api){Style.RESET_ALL}"
            )

            # 构建渠道层原始消息格式
            # metadata 中携带对话所需的额外参数，供 ChannelManager 分发时使用
            raw_message = {
                "user_id": request.conversation_id,
                "content": request.message,
                "metadata": {
                    "service_type": "chat",             # 路由目标：对话服务
                    "conversation_id": request.conversation_id,
                    "system_prompt": request.system_prompt,
                    "model": request.model or get_default_model("openai"),
                    "temperature": request.temperature or 0.7,
                    "max_tokens": request.max_tokens or 2048,
                }
            }

            result = await channel_manager.route_message("rest_api", raw_message)

        else:
            # ── 降级模式：直接调用 ChatService（兼容测试/独立部署）───────
            logger.info(
                f"{Fore.YELLOW}【对话接口】Channel Layer 未就绪，"
                f"降级为直接调用 ChatService{Style.RESET_ALL}"
            )
            result = await chat_service.chat(
                conversation_id=request.conversation_id,
                message=request.message,
                system_prompt=request.system_prompt,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens
            )

        logger.info(f"{Fore.GREEN}【对话接口】对话请求处理成功{Style.RESET_ALL}")

        # 构建标准响应格式
        response = ChatResponse(
            conversation_id=result["conversation_id"],
            message=result["message"],
            model=result["model"],
            usage=result.get("usage")
        )

        return ApiResponseData(
            platform=PlatformEnum.WX_PUBLIC,
            api="/chat",
            data=response.model_dump(),
            ret=["success"],
            v=1
        )

    except Exception as e:
        logger.error(f"{Fore.RED}【对话接口】对话请求处理失败: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail=f"对话处理失败: {str(e)}")


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    流式对话接口

    NOTE: 流式接口直接调用 ChatService.stream_chat()，
    不经过 ChannelManager，因为流式响应需要逐块写入 HTTP 响应，
    无法通过同步 route_message() 进行包装。

    Args:
        request: 对话请求体
        chat_service: 对话服务实例

    Returns:
        StreamingResponse: 服务器推送事件（text/plain）
    """
    logger.info(
        f"{Fore.CYAN}【对话接口】接收到流式对话请求 — "
        f"会话ID: {request.conversation_id}{Style.RESET_ALL}"
    )

    async def generate_stream() -> AsyncIterator[str]:
        """内部生成器：从 ChatService 获取流式响应块"""
        try:
            async for chunk in chat_service.stream_chat(
                conversation_id=request.conversation_id,
                message=request.message,
                system_prompt=request.system_prompt,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens
            ):
                yield chunk

            logger.info(f"{Fore.GREEN}【对话接口】流式对话请求处理完成{Style.RESET_ALL}")

        except Exception as e:
            logger.error(f"{Fore.RED}【对话接口】流式对话请求处理失败: {e}{Style.RESET_ALL}")
            yield f"Error: {str(e)}"

    return StreamingResponse(
        generate_stream(),
        media_type="text/plain"
    )


@router.delete("/chat/{conversation_id}")
async def clear_chat(
    conversation_id: str,
    chat_service: ChatService = Depends(get_chat_service)
) -> ApiResponseData:
    """
    清空对话历史

    Args:
        conversation_id: 要清空的会话 ID
        chat_service: 对话服务实例

    Returns:
        ApiResponseData: 统一响应格式
    """
    logger.info(
        f"{Fore.YELLOW}【对话接口】清空对话历史 — "
        f"会话ID: {conversation_id}{Style.RESET_ALL}"
    )

    try:
        chat_service.clear_conversation(conversation_id)
        logger.info(f"{Fore.GREEN}【对话接口】对话历史清空成功{Style.RESET_ALL}")

        return ApiResponseData(
            platform=PlatformEnum.WX_PUBLIC,
            api=f"/chat/{conversation_id}",
            data={"conversation_id": conversation_id, "status": "cleared"},
            ret=["success"],
            v=1
        )

    except Exception as e:
        logger.error(f"{Fore.RED}【对话接口】清空对话历史失败: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail=f"清空对话历史失败: {str(e)}")
