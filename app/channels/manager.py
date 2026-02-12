from typing import Dict, Any, Optional
from loguru import logger
from colorama import Fore, Style
from app.channels.base import ChannelAdapter, ChannelMessage

class ChannelManager:
    """
    渠道管理器
    
    负责渠道的注册、消息路由和分发
    """
    
    def __init__(self):
        self._adapters: Dict[str, ChannelAdapter] = {}
        logger.info(f"{Fore.BLUE}ChannelManager initialized.{Style.RESET_ALL}")
    
    def register_channel(self, channel_id: str, adapter: ChannelAdapter):
        """
        注册渠道适配器
        
        Args:
            channel_id: 渠道 ID
            adapter: 适配器实例
        """
        self._adapters[channel_id] = adapter
        logger.info(f"Registered channel: {Fore.GREEN}{channel_id}{Style.RESET_ALL}")
    
    def get_adapter(self, channel_id: str) -> Optional[ChannelAdapter]:
        """获取渠道适配器"""
        return self._adapters.get(channel_id)
    
    async def route_message(self, channel_id: str, raw_message: Any):
        """
        路由消息 (入口方法)
        
        Args:
            channel_id: 来源渠道 ID
            raw_message: 原始消息数据
        """
        adapter = self.get_adapter(channel_id)
        if not adapter:
            logger.error(f"{Fore.RED}Channel not found: {channel_id}{Style.RESET_ALL}")
            raise ValueError(f"Channel not found: {channel_id}")
            
        # 1. 接收消息 (标准化)
        try:
            message = await adapter.receive_message(raw_message)
            logger.info(f"Received message from {Fore.CYAN}{channel_id}{Style.RESET_ALL}: {message.message_id}")
        except Exception as e:
            logger.error(f"Failed to receive message from {channel_id}: {e}")
            raise
            
        # 2. 消息分发 (Dispatch)
        # 在 Phase 0 中，我们由于没有完整的 Application Layer，
        # 这里仅模拟分发，实际上应该调用 Application Layer 的入口
        await self._dispatch_to_application(message)
        
    async def _dispatch_to_application(self, message: ChannelMessage):
        """模拟分发到应用层"""
        logger.debug(f"Dispatching message to application: {message.content[:50]}...")
        # TODO: Implement actual dispatch logic to Agent/Chat/Automation Service
