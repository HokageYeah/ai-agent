import pytest
import time
from app.channels.base import ChannelAdapter, ChannelMessage
from app.channels.manager import ChannelManager

class MockAdapter(ChannelAdapter):
    """Mock 适配器"""
    async def receive_message(self, raw_message):
        return ChannelMessage(
            message_id="msg_1",
            channel_id=self.channel_id,
            sender_id="user_1",
            content=str(raw_message),
            timestamp=time.time()
        )
    
    async def send_message(self, message):
        return True

@pytest.mark.asyncio
async def test_channel_manager_routing():
    """测试渠道消息路由"""
    manager = ChannelManager()
    adapter = MockAdapter("test_channel")
    
    # 1. 注册
    manager.register_channel("test_channel", adapter)
    assert manager.get_adapter("test_channel") is not None
    
    # 2. 路由
    # 由于 dispatch 目前是模拟的，我们主要验证 receive_message 被调用且不报错
    await manager.route_message("test_channel", "Hello World")
    
    # 3. 错误处理
    with pytest.raises(ValueError):
        await manager.route_message("unknown_channel", "Hi")
