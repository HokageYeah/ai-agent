"""
测试 Chat Service
==================

测试对话服务的各项功能
"""

import pytest
from app.services.chat_service import ChatService
from app.memory.short_term import ShortTermMemory
from app.core.llm_mock import MockLLM
from app.llm_hub.inference import InferenceEngine
from app.llm_hub.registry import ModelRegistry


@pytest.mark.asyncio
async def test_chat_service_initialization():
    """测试 Chat Service 初始化"""
    # 创建 Mock LLM
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    # 创建 Chat Service
    chat_service = ChatService(llm_hub=inference_engine)
    
    assert chat_service is not None
    assert chat_service.llm_hub is not None
    assert chat_service.memory is not None


@pytest.mark.asyncio
async def test_chat_service_simple_chat():
    """测试简单对话功能"""
    # 创建 Mock LLM
    mock_llm = MockLLM()
    mock_llm.default_response = "你好！我是 AI 助手。"
    
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    # 创建 Chat Service
    chat_service = ChatService(llm_hub=inference_engine)
    
    # 发送消息
    response = await chat_service.chat(
        conversation_id="test_conv_1",
        message="你好"
    )
    
    assert response is not None
    assert "message" in response
    assert response["message"] == "你好！我是 AI 助手。"
    assert response["conversation_id"] == "test_conv_1"


@pytest.mark.asyncio
async def test_chat_service_with_history():
    """测试带历史的对话功能"""
    mock_llm = MockLLM()
    mock_llm.default_response = "我记得你刚才说了你好。"
    
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    chat_service = ChatService(llm_hub=inference_engine)
    
    # 第一次对话
    await chat_service.chat(
        conversation_id="test_conv_2",
        message="你好"
    )
    
    # 第二次对话，应该有历史
    response = await chat_service.chat(
        conversation_id="test_conv_2",
        message="你记得我刚才说什么吗？"
    )
    
    # 验证历史已保存
    history = chat_service.get_conversation_history("test_conv_2")
    assert len(history) >= 2  # 至少有两轮对话


@pytest.mark.asyncio
async def test_chat_service_with_system_prompt():
    """测试带系统提示词的对话"""
    mock_llm = MockLLM()
    mock_llm.default_response = "作为专业的数学老师，我很乐意帮助你。"
    
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    chat_service = ChatService(llm_hub=inference_engine)
    
    response = await chat_service.chat(
        conversation_id="test_conv_3",
        message="请教我数学",
        system_prompt="你是一个专业的数学老师"
    )
    
    assert response is not None
    assert "message" in response


@pytest.mark.asyncio
async def test_clear_conversation():
    """测试清空会话历史"""
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    chat_service = ChatService(llm_hub=inference_engine)
    
    # 发送几条消息
    await chat_service.chat(conversation_id="test_conv_4", message="消息1")
    await chat_service.chat(conversation_id="test_conv_4", message="消息2")
    
    # 验证有历史
    history = chat_service.get_conversation_history("test_conv_4")
    assert len(history) > 0
    
    # 清空历史
    chat_service.clear_conversation("test_conv_4")
    
    # 验证历史已清空
    history = chat_service.get_conversation_history("test_conv_4")
    assert len(history) == 0


@pytest.mark.asyncio
async def test_get_conversation_history():
    """测试获取会话历史"""
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    chat_service = ChatService(llm_hub=inference_engine)
    
    # 发送消息
    await chat_service.chat(conversation_id="test_conv_5", message="测试消息")
    
    # 获取历史
    history = chat_service.get_conversation_history("test_conv_5")
    
    assert isinstance(history, list)
    assert len(history) >= 2  # 用户消息 + 助手回复
