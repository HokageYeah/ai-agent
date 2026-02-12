from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

class ChannelMessage(BaseModel):
    """
    渠道消息通用格式
    """
    message_id: str = Field(..., description="消息唯一标识")
    channel_id: str = Field(..., description="渠道 ID")
    sender_id: str = Field(..., description="发送者 ID")
    content: str = Field(..., description="消息内容")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")
    timestamp: float = Field(..., description="时间戳")

class ChannelAdapter(ABC):
    """
    渠道适配器抽象基类
    
    负责特定渠道的消息接收与发送
    """
    
    def __init__(self, channel_id: str):
        self.channel_id = channel_id
    
    @abstractmethod
    async def receive_message(self, raw_message: Any) -> ChannelMessage:
        """
        接收并转换消息为通用格式
        
        Args:
            raw_message: 渠道原始消息
            
        Returns:
            ChannelMessage: 通用消息对象
        """
        pass
    
    @abstractmethod
    async def send_message(self, message: ChannelMessage) -> bool:
        """
        发送消息
        
        Args:
            message: 通用消息对象
            
        Returns:
            bool: 发送是否成功
        """
        pass
