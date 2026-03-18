"""
Chat Service (对话服务)
================================

本模块提供对话服务功能。

功能特点：
1. 处理单次对话请求
2. 管理对话历史上下文
3. 支持流式响应生成
4. 集成短期记忆系统

作者: AI Agent Team
创建时间: 2026-02-15
"""

from typing import Dict, List, Any, Optional, AsyncIterator
from loguru import logger
from colorama import Fore, Style

from app.core.config import get_default_model
from app.memory.short_term import ShortTermMemory


class ChatService:
    """
    对话服务
    
    提供对话功能，包括上下文管理和流式响应
    """
    
    def __init__(self, llm_hub, memory: Optional[ShortTermMemory] = None):
        """
        初始化对话服务
        
        Args:
            llm_hub: LLM Hub 实例 (InferenceEngine)
            memory: 短期记忆实例，如果为 None 则创建新实例
        """
        self.llm_hub = llm_hub
        self.memory = memory or ShortTermMemory(max_messages=10)
        
        logger.info(f"{Fore.GREEN}对话服务初始化完成{Style.RESET_ALL}")
    
    async def chat(
        self,
        conversation_id: str,
        message: str,
        system_prompt: Optional[str] = None,
        **config_kwargs
    ) -> Dict[str, Any]:
        """
        处理对话请求
        
        Args:
            conversation_id: 会话 ID
            message: 用户消息
            system_prompt: 系统提示词（可选）
            **config_kwargs: LLM 配置参数
            
        Returns:
            Dict[str, Any]: 包含响应内容的字典
        """
        logger.info(
            f"{Fore.BLUE}处理对话请求 - 会话ID: {conversation_id}{Style.RESET_ALL}"
        )
        logger.info(f"{Fore.CYAN}用户消息: {message}{Style.RESET_ALL}")
        
        try:
            # 1. 获取历史上下文
            context = self.memory.get_context(conversation_id)
            logger.debug(
                f"{Fore.CYAN}获取到 {len(context)} 条历史消息{Style.RESET_ALL}"
            )
            
            # 2. 构建消息列表
            messages = []
            
            # 添加系统提示词（如果提供）
            if system_prompt:
                messages.append({
                    "role": "system",
                    "content": system_prompt
                })
                logger.debug(f"{Fore.CYAN}添加系统提示词{Style.RESET_ALL}")
            
            # 添加历史上下文
            messages.extend(context)
            
            # 添加当前用户消息
            messages.append({
                "role": "user",
                "content": message
            })
            
            logger.debug(
                f"{Fore.CYAN}构建消息列表，共 {len(messages)} 条消息{Style.RESET_ALL}"
            )
            
            # 3. 调用 LLM 推理
            from app.llm_hub.inference import InferenceConfig
            
            config = InferenceConfig(
                model=config_kwargs.get("model") or get_default_model("openai"),
                temperature=config_kwargs.get("temperature", 0.7),
                max_tokens=config_kwargs.get("max_tokens", 2048)
            )
            
            logger.info(f"{Fore.BLUE}调用 LLM 进行推理...{Style.RESET_ALL}")
            
            response = await self.llm_hub.infer(
                messages=messages,
                config=config
            )
            
            # 4. 更新记忆
            self.memory.add_message(
                conversation_id,
                {"role": "user", "content": message}
            )
            self.memory.add_message(
                conversation_id,
                {"role": "assistant", "content": response.content}
            )
            
            logger.info(f"{Fore.GREEN}对话处理成功{Style.RESET_ALL}")
            logger.debug(f"{Fore.GREEN}响应: {response.content[:100]}...{Style.RESET_ALL}")
            
            # 5. 返回响应
            return {
                "conversation_id": conversation_id,
                "message": response.content,
                "model": response.model,
                "usage": response.usage
            }
            
        except Exception as e:
            logger.error(f"{Fore.RED}对话处理失败: {e}{Style.RESET_ALL}")
            raise
    
    async def stream_chat(
        self,
        conversation_id: str,
        message: str,
        system_prompt: Optional[str] = None,
        **config_kwargs
    ) -> AsyncIterator[str]:
        """
        处理流式对话请求
        
        Args:
            conversation_id: 会话 ID
            message: 用户消息
            system_prompt: 系统提示词（可选）
            **config_kwargs: LLM 配置参数
            
        Yields:
            str: 流式响应的文本片段
        """
        logger.info(
            f"{Fore.BLUE}处理流式对话请求 - 会话ID: {conversation_id}{Style.RESET_ALL}"
        )
        logger.info(f"{Fore.CYAN}用户消息: {message}{Style.RESET_ALL}")
        
        try:
            # 1. 获取历史上下文
            context = self.memory.get_context(conversation_id)
            
            # 2. 构建消息列表
            messages = []
            
            if system_prompt:
                messages.append({
                    "role": "system",
                    "content": system_prompt
                })
            
            messages.extend(context)
            messages.append({
                "role": "user",
                "content": message
            })
            
            # 3. 调用 LLM 流式推理
            from app.llm_hub.inference import InferenceConfig
            
            config = InferenceConfig(
                model=config_kwargs.get("model") or get_default_model("openai"),
                temperature=config_kwargs.get("temperature", 0.7),
                max_tokens=config_kwargs.get("max_tokens", 2048),
                stream=True
            )
            
            logger.info(f"{Fore.BLUE}开始流式推理...{Style.RESET_ALL}")
            
            # 收集完整响应用于更新记忆
            full_response = ""
            
            # 4. 流式返回响应
            async for chunk in self.llm_hub.infer_stream(messages=messages, config=config):
                if chunk.content:
                    full_response += chunk.content
                    yield chunk.content
            
            # 5. 更新记忆
            self.memory.add_message(
                conversation_id,
                {"role": "user", "content": message}
            )
            self.memory.add_message(
                conversation_id,
                {"role": "assistant", "content": full_response}
            )
            
            logger.info(f"{Fore.GREEN}流式对话处理完成{Style.RESET_ALL}")
            
        except Exception as e:
            logger.error(f"{Fore.RED}流式对话处理失败: {e}{Style.RESET_ALL}")
            raise
    
    def clear_conversation(self, conversation_id: str):
        """
        清空会话历史
        
        Args:
            conversation_id: 会话 ID
        """
        logger.info(
            f"{Fore.YELLOW}清空会话历史 - 会话ID: {conversation_id}{Style.RESET_ALL}"
        )
        self.memory.clear(conversation_id)
    
    def get_conversation_history(self, conversation_id: str) -> List[Dict[str, Any]]:
        """
        获取会话历史
        
        Args:
            conversation_id: 会话 ID
            
        Returns:
            List[Dict[str, Any]]: 会话历史消息列表
        """
        logger.debug(
            f"{Fore.CYAN}获取会话历史 - 会话ID: {conversation_id}{Style.RESET_ALL}"
        )
        return self.memory.get_context(conversation_id)


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Chat Service 测试{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
    
    # 测试需要异步环境
    print(f"{Fore.YELLOW}请使用 pytest 运行测试{Style.RESET_ALL}")
    
    print(f"\n{Fore.GREEN}模块加载成功!{Style.RESET_ALL}\n")
