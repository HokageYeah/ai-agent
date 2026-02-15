"""
测试 REST API Adapter
==================

测试 REST API 渠道适配器
"""

import pytest
from app.channels.adapters.rest_api import RESTAPIAdapter
from app.channels.base import ChannelMessage


@pytest.mark.asyncio
async def test_rest_api_adapter_initialization():
    """测试 REST API Adapter 初始化"""
    adapter = RESTAPIAdapter()
    
    assert adapter is not None
    assert adapter.channel_id == "rest_api"


@pytest.mark.asyncio
async def test_receive_message():
    """测试接收消息"""
    adapter = RESTAPIAdapter()
    
    raw_message = {
        "user_id": "user123",
        "content": "Hello, AI!",
        "metadata": {"source": "web"}
    }
    
    message = await adapter.receive_message(raw_message)
    
    assert isinstance(message, ChannelMessage)
    assert message.sender_id == "user123"
    assert message.content == "Hello, AI!"
    assert message.channel_id == "rest_api"
    assert message.metadata["source"] == "web"


@pytest.mark.asyncio
async def test_receive_message_without_user_id():
    """测试接收没有 user_id 的消息"""
    adapter = RESTAPIAdapter()
    
    raw_message = {
        "content": "Hello!"
    }
    
    message = await adapter.receive_message(raw_message)
    
    assert message.sender_id == "anonymous"


@pytest.mark.asyncio
async def test_receive_invalid_message():
    """测试接收无效消息"""
    adapter = RESTAPIAdapter()
    
    # 缺少 content 字段
    raw_message = {
        "user_id": "user123"
    }
    
    with pytest.raises(ValueError, match="Missing required field: content"):
        await adapter.receive_message(raw_message)


@pytest.mark.asyncio
async def test_send_message():
    """测试发送消息"""
    adapter = RESTAPIAdapter()
    
    message = ChannelMessage(
        message_id="msg123",
        channel_id="rest_api",
        sender_id="assistant",
        content="Hello, User!",
        metadata={},
        timestamp=1234567890.0
    )
    
    success = await adapter.send_message(message)
    
    assert success is True


@pytest.mark.asyncio
async def test_format_response():
    """测试格式化响应"""
    adapter = RESTAPIAdapter()
    
    message = ChannelMessage(
        message_id="msg123",
        channel_id="rest_api",
        sender_id="assistant",
        content="Response content",
        metadata={"type": "response"},
        timestamp=1234567890.0
    )
    
    response = adapter.format_response(message)
    
    assert isinstance(response, dict)
    assert response["message_id"] == "msg123"
    assert response["content"] == "Response content"
    assert response["channel_id"] == "rest_api"
    assert response["metadata"]["type"] == "response"
