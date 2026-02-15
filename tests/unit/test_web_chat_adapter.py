"""
测试 Web Chat Adapter
==================

测试 Web Chat 渠道适配器
"""

import pytest
import json
from app.channels.adapters.web_chat import WebChatAdapter
from app.channels.base import ChannelMessage


@pytest.mark.asyncio
async def test_web_chat_adapter_initialization():
    """测试 Web Chat Adapter 初始化"""
    adapter = WebChatAdapter()
    
    assert adapter is not None
    assert adapter.channel_id == "web_chat"
    assert adapter.connections == {}


@pytest.mark.asyncio
async def test_receive_message_from_dict():
    """测试从字典接收消息"""
    adapter = WebChatAdapter()
    
    raw_message = {
        "user_id": "user123",
        "content": "Hello, AI!",
        "metadata": {"browser": "Chrome"}
    }
    
    message = await adapter.receive_message(raw_message)
    
    assert isinstance(message, ChannelMessage)
    assert message.sender_id == "user123"
    assert message.content == "Hello, AI!"
    assert message.metadata["browser"] == "Chrome"


@pytest.mark.asyncio
async def test_receive_message_from_json():
    """测试从 JSON 字符串接收消息"""
    adapter = WebChatAdapter()
    
    raw_message = json.dumps({
        "user_id": "user456",
        "content": "Test message",
        "metadata": {}
    })
    
    message = await adapter.receive_message(raw_message)
    
    assert isinstance(message, ChannelMessage)
    assert message.sender_id == "user456"
    assert message.content == "Test message"


@pytest.mark.asyncio
async def test_receive_invalid_json():
    """测试接收无效 JSON"""
    adapter = WebChatAdapter()
    
    raw_message = "This is not valid JSON"
    
    with pytest.raises(json.JSONDecodeError):
        await adapter.receive_message(raw_message)


@pytest.mark.asyncio
async def test_send_message():
    """测试发送消息"""
    adapter = WebChatAdapter()
    
    message = ChannelMessage(
        message_id="msg123",
        channel_id="web_chat",
        sender_id="assistant",
        content="Hello!",
        metadata={},
        timestamp=1234567890.0
    )
    
    success = await adapter.send_message(message)
    
    assert success is True


@pytest.mark.asyncio
async def test_serialize_message():
    """测试消息序列化"""
    adapter = WebChatAdapter()
    
    message = ChannelMessage(
        message_id="msg123",
        channel_id="web_chat",
        sender_id="assistant",
        content="Test content",
        metadata={"key": "value"},
        timestamp=1234567890.0
    )
    
    serialized = adapter.serialize_message(message)
    
    assert isinstance(serialized, str)
    
    # 验证可以反序列化
    deserialized = json.loads(serialized)
    assert deserialized["message_id"] == "msg123"
    assert deserialized["content"] == "Test content"


@pytest.mark.asyncio
async def test_deserialize_message():
    """测试消息反序列化"""
    adapter = WebChatAdapter()
    
    message_json = json.dumps({
        "message_id": "msg456",
        "channel_id": "web_chat",
        "sender_id": "user",
        "content": "Hello",
        "metadata": {},
        "timestamp": 1234567890.0
    })
    
    deserialized = adapter.deserialize_message(message_json)
    
    assert isinstance(deserialized, dict)
    assert deserialized["message_id"] == "msg456"
    assert deserialized["content"] == "Hello"


@pytest.mark.asyncio
async def test_connection_management():
    """测试连接管理"""
    adapter = WebChatAdapter()
    
    # 模拟 WebSocket 对象
    mock_websocket = {"id": "ws123"}
    
    # 注册连接
    adapter.register_connection("conn1", mock_websocket)
    
    assert "conn1" in adapter.connections
    assert adapter.get_connection("conn1") == mock_websocket
    
    # 注销连接
    adapter.unregister_connection("conn1")
    
    assert "conn1" not in adapter.connections
    assert adapter.get_connection("conn1") is None
