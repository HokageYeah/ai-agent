"""
Web Chat Channel Adapter (Web Chat 渠道适配器)
================================

本模块实现 Web Chat 渠道适配器。

功能特点：
1. 接收 WebSocket 消息并转换为通用格式
2. 将响应转换为 WebSocket 消息
3. 支持实时双向通信
4. 处理消息序列化和反序列化

作者: AI Agent Team
创建时间: 2026-02-15
"""

from typing import Dict, Any, Optional
import time
import uuid
import json
from loguru import logger
from colorama import Fore, Style

from app.channels.base import ChannelAdapter, ChannelMessage


class WebChatAdapter(ChannelAdapter):
    """
    Web Chat 渠道适配器
    
    将 WebSocket 消息转换为通用消息格式
    """
    
    def __init__(self, channel_id: str = "web_chat"):
        """
        初始化 Web Chat 适配器
        
        Args:
            channel_id: 渠道 ID
        """
        super().__init__(channel_id)
        # WebSocket 连接字典 {connection_id: websocket}
        self.connections: Dict[str, Any] = {}
        
        logger.info(
            f"{Fore.GREEN}Web Chat 渠道适配器初始化完成 - ID: {channel_id}{Style.RESET_ALL}"
        )
    
    async def receive_message(self, raw_message: Any) -> ChannelMessage:
        """
        接收并转换 WebSocket 消息为通用消息格式
        
        Args:
            raw_message: WebSocket 消息数据，可以是：
                - JSON 字符串
                - 字典对象
                
        Returns:
            ChannelMessage: 通用消息对象
        """
        logger.info(
            f"{Fore.BLUE}[Web Chat] 接收消息{Style.RESET_ALL}"
        )
        
        try:
            # 解析消息
            if isinstance(raw_message, str):
                # JSON 字符串，需要解析
                logger.debug(f"{Fore.CYAN}[Web Chat] 解析 JSON 消息{Style.RESET_ALL}")
                message_data = json.loads(raw_message)
            elif isinstance(raw_message, dict):
                # 已经是字典
                message_data = raw_message
            else:
                raise ValueError(f"Unsupported message type: {type(raw_message)}")
            
            # 验证必需字段
            if "content" not in message_data:
                raise ValueError("Missing required field: content")
            
            # 提取消息信息
            user_id = message_data.get("user_id", "anonymous")
            content = message_data["content"]
            metadata = message_data.get("metadata", {})
            
            # 生成消息 ID
            message_id = message_data.get("message_id") or str(uuid.uuid4())
            
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
                f"{Fore.GREEN}[Web Chat] 消息接收成功 - "
                f"ID: {message_id}, 用户: {user_id}{Style.RESET_ALL}"
            )
            logger.debug(f"{Fore.CYAN}[Web Chat] 消息内容: {content[:100]}...{Style.RESET_ALL}")
            
            return message
            
        except json.JSONDecodeError as e:
            logger.error(
                f"{Fore.RED}[Web Chat] JSON 解析失败: {e}{Style.RESET_ALL}"
            )
            raise
        except Exception as e:
            logger.error(
                f"{Fore.RED}[Web Chat] 消息接收失败: {e}{Style.RESET_ALL}"
            )
            raise
    
    async def send_message(self, message: ChannelMessage) -> bool:
        """
        发送消息（通过 WebSocket）
        
        Args:
            message: 通用消息对象
            
        Returns:
            bool: 发送是否成功
        """
        logger.info(
            f"{Fore.BLUE}[Web Chat] 发送消息 - ID: {message.message_id}{Style.RESET_ALL}"
        )
        
        try:
            # 序列化消息
            message_json = self.serialize_message(message)
            
            logger.info(
                f"{Fore.GREEN}[Web Chat] 消息序列化完成{Style.RESET_ALL}"
            )
            logger.debug(
                f"{Fore.CYAN}[Web Chat] 消息: {message_json[:200]}...{Style.RESET_ALL}"
            )
            
            # 注意：实际的 WebSocket 发送由外部 WebSocket 处理器完成
            # 这里只负责消息的序列化
            
            return True
            
        except Exception as e:
            logger.error(
                f"{Fore.RED}[Web Chat] 消息发送失败: {e}{Style.RESET_ALL}"
            )
            return False
    
    def serialize_message(self, message: ChannelMessage) -> str:
        """
        序列化消息为 JSON 字符串
        
        Args:
            message: 通用消息对象
            
        Returns:
            str: JSON 字符串
        """
        logger.debug(
            f"{Fore.CYAN}[Web Chat] 序列化消息{Style.RESET_ALL}"
        )
        
        message_dict = {
            "message_id": message.message_id,
            "channel_id": message.channel_id,
            "sender_id": message.sender_id,
            "content": message.content,
            "metadata": message.metadata,
            "timestamp": message.timestamp
        }
        
        return json.dumps(message_dict, ensure_ascii=False)
    
    def deserialize_message(self, message_json: str) -> Dict[str, Any]:
        """
        反序列化 JSON 字符串为消息字典
        
        Args:
            message_json: JSON 字符串
            
        Returns:
            Dict[str, Any]: 消息字典
        """
        logger.debug(
            f"{Fore.CYAN}[Web Chat] 反序列化消息{Style.RESET_ALL}"
        )
        
        return json.loads(message_json)
    
    def register_connection(self, connection_id: str, websocket: Any):
        """
        注册 WebSocket 连接
        
        Args:
            connection_id: 连接 ID
            websocket: WebSocket 对象
        """
        logger.info(
            f"{Fore.GREEN}[Web Chat] 注册连接 - ID: {connection_id}{Style.RESET_ALL}"
        )
        self.connections[connection_id] = websocket
    
    def unregister_connection(self, connection_id: str):
        """
        注销 WebSocket 连接
        
        Args:
            connection_id: 连接 ID
        """
        logger.info(
            f"{Fore.YELLOW}[Web Chat] 注销连接 - ID: {connection_id}{Style.RESET_ALL}"
        )
        if connection_id in self.connections:
            del self.connections[connection_id]
    
    def get_connection(self, connection_id: str) -> Optional[Any]:
        """
        获取 WebSocket 连接
        
        Args:
            connection_id: 连接 ID
            
        Returns:
            Optional[Any]: WebSocket 对象或 None
        """
        return self.connections.get(connection_id)


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Web Chat Adapter 测试{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
    
    # 测试需要异步环境
    print(f"{Fore.YELLOW}请使用 pytest 运行测试{Style.RESET_ALL}")
    
    print(f"\n{Fore.GREEN}模块加载成功!{Style.RESET_ALL}\n")
