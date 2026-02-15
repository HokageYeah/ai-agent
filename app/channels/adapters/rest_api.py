"""
REST API Channel Adapter (REST API 渠道适配器)
================================

本模块实现 REST API 渠道适配器。

功能特点：
1. 接收 HTTP 请求并转换为通用消息格式
2. 将响应转换为 HTTP 响应格式
3. 支持标准的 REST API 调用

作者: AI Agent Team
创建时间: 2026-02-15
"""

from typing import Dict, Any, Optional
import time
import uuid
from loguru import logger
from colorama import Fore, Style

from app.channels.base import ChannelAdapter, ChannelMessage


class RESTAPIAdapter(ChannelAdapter):
    """
    REST API 渠道适配器
    
    将 HTTP 请求/响应转换为通用消息格式
    """
    
    def __init__(self, channel_id: str = "rest_api"):
        """
        初始化 REST API 适配器
        
        Args:
            channel_id: 渠道 ID
        """
        super().__init__(channel_id)
        logger.info(
            f"{Fore.GREEN}REST API 渠道适配器初始化完成 - ID: {channel_id}{Style.RESET_ALL}"
        )
    
    async def receive_message(self, raw_message: Any) -> ChannelMessage:
        """
        接收并转换 HTTP 请求为通用消息格式
        
        Args:
            raw_message: HTTP 请求数据，应包含：
                - user_id: 用户 ID
                - content: 消息内容
                - metadata: 元数据（可选）
                
        Returns:
            ChannelMessage: 通用消息对象
        """
        logger.info(
            f"{Fore.BLUE}[REST API] 接收消息{Style.RESET_ALL}"
        )
        
        try:
            # 验证请求数据
            if not isinstance(raw_message, dict):
                raise ValueError("Invalid message format: expected dict")
            
            if "content" not in raw_message:
                raise ValueError("Missing required field: content")
            
            # 提取消息信息
            user_id = raw_message.get("user_id", "anonymous")
            content = raw_message["content"]
            metadata = raw_message.get("metadata", {})
            
            # 生成消息 ID
            message_id = raw_message.get("message_id") or str(uuid.uuid4())
            
            # 创建通用消息对象
            message = ChannelMessage(
                message_id=message_id,
                channel_id=self.channel_id,
                sender_id=user_id,
                content=content,
                metadata=metadata,
                timestamp=time.time()
            )
            
            logger.info(
                f"{Fore.GREEN}[REST API] 消息接收成功 - "
                f"ID: {message_id}, 用户: {user_id}{Style.RESET_ALL}"
            )
            logger.debug(f"{Fore.CYAN}[REST API] 消息内容: {content[:100]}...{Style.RESET_ALL}")
            
            return message
            
        except Exception as e:
            logger.error(
                f"{Fore.RED}[REST API] 消息接收失败: {e}{Style.RESET_ALL}"
            )
            raise
    
    async def send_message(self, message: ChannelMessage) -> bool:
        """
        发送消息（转换为 HTTP 响应格式）
        
        Args:
            message: 通用消息对象
            
        Returns:
            bool: 发送是否成功
        """
        logger.info(
            f"{Fore.BLUE}[REST API] 发送消息 - ID: {message.message_id}{Style.RESET_ALL}"
        )
        
        try:
            # REST API 适配器不直接发送消息
            # 而是将消息内容返回给调用方
            # 实际的 HTTP 响应由 API 端点处理
            
            logger.info(
                f"{Fore.GREEN}[REST API] 消息准备完成{Style.RESET_ALL}"
            )
            logger.debug(
                f"{Fore.CYAN}[REST API] 消息内容: {message.content[:100]}...{Style.RESET_ALL}"
            )
            
            return True
            
        except Exception as e:
            logger.error(
                f"{Fore.RED}[REST API] 消息发送失败: {e}{Style.RESET_ALL}"
            )
            return False
    
    def format_response(self, message: ChannelMessage) -> Dict[str, Any]:
        """
        将通用消息格式化为 HTTP 响应
        
        Args:
            message: 通用消息对象
            
        Returns:
            Dict[str, Any]: HTTP 响应数据
        """
        logger.debug(
            f"{Fore.CYAN}[REST API] 格式化响应{Style.RESET_ALL}"
        )
        
        return {
            "message_id": message.message_id,
            "content": message.content,
            "channel_id": message.channel_id,
            "timestamp": message.timestamp,
            "metadata": message.metadata
        }


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}REST API Adapter 测试{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
    
    # 测试需要异步环境
    print(f"{Fore.YELLOW}请使用 pytest 运行测试{Style.RESET_ALL}")
    
    print(f"\n{Fore.GREEN}模块加载成功!{Style.RESET_ALL}\n")
