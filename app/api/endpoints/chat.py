"""
Chat API Endpoints (对话接口)
================================

本模块提供对话相关的 REST API 端点。

功能特点：
1. POST /chat - 普通对话接口
2. POST /chat/stream - 流式对话接口
3. DELETE /chat/{conversation_id} - 清空对话历史

作者: AI Agent Team
创建时间: 2026-02-17
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from typing import AsyncIterator
from loguru import logger
from colorama import Fore, Style

from app.schemas.agent_data import ChatRequest, ChatResponse
from app.schemas.common_data import ApiResponseData, PlatformEnum
from app.services.chat_service import ChatService
from app.llm_hub.inference import InferenceEngine
from app.memory.short_term import ShortTermMemory

# 创建路由器
router = APIRouter()

# 全局服务实例（后续可以通过依赖注入管理）
_chat_service: ChatService = None


def get_chat_service() -> ChatService:
    """
    获取 ChatService 实例（依赖注入）
    
    Returns:
        ChatService: 对话服务实例
    """
    global _chat_service
    if _chat_service is None:
        logger.info(f"{Fore.BLUE}初始化 ChatService...{Style.RESET_ALL}")
        
        # 创建推理引擎所需的依赖
        from app.llm_hub.providers.openai import OpenAIProvider
        from app.llm_hub.registry import ModelRegistry
        from app.core.config import settings
        
        # 创建默认 Provider
        provider = OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL
        )
        
        # 创建模型注册中心
        model_registry = ModelRegistry()
        
        # 创建推理引擎
        inference_engine = InferenceEngine(
            provider=provider,
            model_registry=model_registry
        )
        
        # 创建短期记忆
        memory = ShortTermMemory(max_messages=10)
        
        # 创建对话服务
        _chat_service = ChatService(llm_hub=inference_engine, memory=memory)
        logger.info(f"{Fore.GREEN}ChatService 初始化完成{Style.RESET_ALL}")
    
    return _chat_service


@router.post("/chat")
async def chat(
    request: ChatRequest,
    chat_service: ChatService = Depends(get_chat_service)
) -> ApiResponseData:
    """
    普通对话接口
    
    Args:
        request: 对话请求
        chat_service: 对话服务实例
        
    Returns:
        ApiResponseData: 统一响应格式
    """
    logger.info(f"{Fore.CYAN}接收到对话请求 - 会话ID: {request.conversation_id}{Style.RESET_ALL}")
    
    try:
        # 调用对话服务
        result = await chat_service.chat(
            conversation_id=request.conversation_id,
            message=request.message,
            system_prompt=request.system_prompt,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens
        )
        
        logger.info(f"{Fore.GREEN}对话请求处理成功{Style.RESET_ALL}")
        
        # 构建响应（使用项目统一格式）
        response = ChatResponse(
            conversation_id=result["conversation_id"],
            message=result["message"],
            model=result["model"],
            usage=result.get("usage")
        )
        
        return ApiResponseData(
            platform=PlatformEnum.WX_PUBLIC,  # 使用现有枚举
            api="/chat",
            data=response.model_dump(),
            ret=["success"],
            v=1
        )
        
    except Exception as e:
        logger.error(f"{Fore.RED}对话请求处理失败: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail=f"对话处理失败: {str(e)}")


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    流式对话接口
    
    Args:
        request: 对话请求
        chat_service: 对话服务实例
        
    Returns:
        StreamingResponse: 流式响应
    """
    logger.info(f"{Fore.CYAN}接收到流式对话请求 - 会话ID: {request.conversation_id}{Style.RESET_ALL}")
    
    async def generate_stream() -> AsyncIterator[str]:
        """生成流式响应"""
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
                
            logger.info(f"{Fore.GREEN}流式对话请求处理完成{Style.RESET_ALL}")
            
        except Exception as e:
            logger.error(f"{Fore.RED}流式对话请求处理失败: {e}{Style.RESET_ALL}")
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
        conversation_id: 会话 ID
        chat_service: 对话服务实例
        
    Returns:
        ApiResponseData: 统一响应格式
    """
    logger.info(f"{Fore.YELLOW}清空对话历史 - 会话ID: {conversation_id}{Style.RESET_ALL}")
    
    try:
        # 清空会话
        chat_service.clear_conversation(conversation_id)
        
        logger.info(f"{Fore.GREEN}对话历史清空成功{Style.RESET_ALL}")
        
        return ApiResponseData(
            platform=PlatformEnum.WX_PUBLIC,
            api=f"/chat/{conversation_id}",
            data={"conversation_id": conversation_id, "status": "cleared"},
            ret=["success"],
            v=1
        )
        
    except Exception as e:
        logger.error(f"{Fore.RED}清空对话历史失败: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail=f"清空对话历史失败: {str(e)}")
