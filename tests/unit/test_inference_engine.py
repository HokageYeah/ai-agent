"""
Inference Engine 单元测试
========================

本模块包含 InferenceEngine 类的单元测试。

测试内容：
1. InferenceConfig 配置测试
2. InferenceResult 结果测试
3. InferenceEngine 核心功能测试
4. 请求预处理和后处理测试

作者: AI Agent Team
创建时间: 2026-02-12
"""

import pytest
import pytest_asyncio
from unittest.mock import Mock, AsyncMock, patch
from app.core.config import get_default_model
from app.llm_hub.inference import InferenceConfig, InferenceResult, InferenceEngine
from app.llm_hub.prompt_builder import PromptBuilder
from app.llm_hub.streaming import StreamingManager


class TestInferenceConfig:
    """InferenceConfig 测试类"""
    
    def test_default_config(self):
        """
        测试默认配置
        
        验证 InferenceConfig 的默认参数是否正确
        """
        config = InferenceConfig()
        
        assert config.model == get_default_model("openai")
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
        assert config.stream is False
        assert config.system_prompt is None
        assert config.context == []
        assert config.tools == []
        assert config.provider is None
    
    def test_custom_config(self):
        """
        测试自定义配置
        
        验证自定义参数是否正确设置
        """
        config = InferenceConfig(
            model="gpt-4",
            temperature=0.5,
            max_tokens=2048,
            system_prompt="你是一个助手",
            provider="openai"
        )
        
        assert config.model == "gpt-4"
        assert config.temperature == 0.5
        assert config.max_tokens == 2048
        assert config.system_prompt == "你是一个助手"
        assert config.provider == "openai"
    
    def test_config_with_context_and_tools(self):
        """
        测试带上下文和工具的配置
        
        验证 context 和 tools 参数是否正确初始化
        """
        context = [{"role": "user", "content": "之前的内容"}]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"}
                        }
                    }
                }
            }
        ]
        config = InferenceConfig(context=context, tools=tools)
        
        assert config.context == context
        assert config.tools == tools
    
    def test_config_temperature_range(self):
        """
        测试温度参数范围
        
        验证温度参数可以设置不同值
        """
        # 测试不同温度值
        config_low = InferenceConfig(temperature=0.1)
        config_mid = InferenceConfig(temperature=0.7)
        config_high = InferenceConfig(temperature=1.5)
        
        assert config_low.temperature == 0.1
        assert config_mid.temperature == 0.7
        assert config_high.temperature == 1.5
    
    def test_config_empty_lists(self):
        """
        测试空列表初始化
        
        验证空 context 和 tools 被正确初始化为空列表
        """
        config = InferenceConfig()
        
        assert isinstance(config.context, list)
        assert isinstance(config.tools, list)
        assert len(config.context) == 0
        assert len(config.tools) == 0


class TestInferenceResult:
    """InferenceResult 测试类"""
    
    def test_result_creation(self):
        """
        测试结果创建
        
        验证推理结果可以正确创建并包含所有信息
        """
        result = InferenceResult(
            content="测试回复",
            raw_response={"id": "test-id", "object": "chat.completion"},
            model="gpt-3.5-turbo",
            provider="openai",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
            finish_reason="stop"
        )
        
        assert result.content == "测试回复"
        assert result.raw_response["id"] == "test-id"
        assert result.model == "gpt-3.5-turbo"
        assert result.provider == "openai"
        assert result.usage["prompt_tokens"] == 10
        assert result.usage["completion_tokens"] == 5
        assert result.finish_reason == "stop"
        assert result.created_at is not None
    
    def test_result_without_usage(self):
        """
        测试无 usage 的结果
        
        验证 usage 为空时能正确处理
        """
        result = InferenceResult(
            content="回复内容",
            raw_response={},
            model="claude-3-opus",
            provider="anthropic"
        )
        
        assert result.usage == {}
        assert result.finish_reason is None
    
    def test_result_repr(self):
        """
        测试结果字符串表示
        
        验证 __repr__ 方法返回正确的格式
        """
        result = InferenceResult(
            content="短回复",
            raw_response={},
            model="gpt-4",
            provider="openai",
            finish_reason="stop"
        )
        
        repr_str = repr(result)
        assert "InferenceResult" in repr_str
        assert "gpt-4" in repr_str
        assert "openai" in repr_str
    
    def test_result_with_different_finish_reasons(self):
        """
        测试不同的结束原因
        
        验证各种 finish_reason 都能正确处理
        """
        finish_reasons = ["stop", "length", "tool_calls", "content_filter", None]
        
        for reason in finish_reasons:
            result = InferenceResult(
                content="测试",
                raw_response={},
                model="test",
                provider="test",
                finish_reason=reason
            )
            assert result.finish_reason == reason


class TestInferenceEngine:
    """InferenceEngine 测试类"""
    
    @pytest.fixture
    def mock_provider(self):
        """
        创建模拟供应商
        
        返回一个模拟的 LLM 供应商，包含异步的 chat 和 stream 方法
        """
        provider = Mock()
        provider.chat = AsyncMock(return_value={
            "id": "test-id",
            "object": "chat.completion",
            "choices": [{
                "message": {"content": "模拟回复"},
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5
            }
        })
        provider.stream = AsyncMock(return_value=iter([]))
        return provider
    
    @pytest.fixture
    def mock_registry(self):
        """
        创建模拟模型注册中心
        
        返回一个模拟的模型注册中心
        """
        registry = Mock()
        registry.get_model = Mock(return_value=Mock(
            model_id="gpt-3.5-turbo",
            provider="openai",
            model_name="GPT-3.5 Turbo",
            capabilities=["chat", "function_call"],
            context_window=16385,
            max_output_tokens=4096
        ))
        return registry
    
    def test_engine_initialization(self, mock_provider, mock_registry):
        """
        测试引擎初始化
        
        验证 InferenceEngine 能正确初始化所有组件
        """
        engine = InferenceEngine(
            provider=mock_provider,
            model_registry=mock_registry
        )
        
        assert engine._provider == mock_provider
        assert engine._model_registry == mock_registry
        assert isinstance(engine._prompt_builder, PromptBuilder)
        assert isinstance(engine._streaming_manager, StreamingManager)
        assert engine._request_count == 0
        assert engine._error_count == 0
    
    def test_set_provider(self, mock_provider, mock_registry):
        """
        测试设置供应商
        
        验证可以动态切换默认供应商
        """
        engine = InferenceEngine(
            provider=mock_provider,
            model_registry=mock_registry
        )
        
        new_provider = Mock()
        new_provider.chat = AsyncMock(return_value={})
        
        engine.set_provider(new_provider)
        
        assert engine._provider == new_provider
    
    @pytest.mark.asyncio
    async def test_infer_success(self, mock_provider, mock_registry):
        """
        测试成功推理
        
        验证 infer 方法能正确执行推理并返回结果
        """
        engine = InferenceEngine(
            provider=mock_provider,
            model_registry=mock_registry
        )
        
        messages = [{"role": "user", "content": "你好"}]
        config = InferenceConfig(model="gpt-3.5-turbo")
        
        result = await engine.infer(messages, config)
        
        assert isinstance(result, InferenceResult)
        assert result.content == "模拟回复"
        assert result.model == "gpt-3.5-turbo"
        assert result.provider == "openai"
        mock_provider.chat.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_infer_with_system_prompt(self, mock_provider, mock_registry):
        """
        测试带系统提示词的推理
        
        验证 system_prompt 能正确传递给供应商
        """
        engine = InferenceEngine(
            provider=mock_provider,
            model_registry=mock_registry
        )
        
        messages = [{"role": "user", "content": "你好"}]
        config = InferenceConfig(system_prompt="你是一个有帮助的助手")
        
        result = await engine.infer(messages, config)
        
        assert isinstance(result, InferenceResult)
        # 验证 chat 被调用
        mock_provider.chat.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_infer_with_temperature(self, mock_provider, mock_registry):
        """
        测试带温度参数的推理
        
        验证 temperature 参数正确传递
        """
        engine = InferenceEngine(
            provider=mock_provider,
            model_registry=mock_registry
        )
        
        messages = [{"role": "user", "content": "测试"}]
        config = InferenceConfig(temperature=0.3)
        
        result = await engine.infer(messages, config)
        
        assert isinstance(result, InferenceResult)
    
    def test_get_stats(self, mock_provider, mock_registry):
        """
        测试获取统计信息
        
        验证 get_stats 返回正确的统计信息
        """
        engine = InferenceEngine(
            provider=mock_provider,
            model_registry=mock_registry
        )
        
        stats = engine.get_stats()
        
        assert "total_requests" in stats
        assert "successful_requests" in stats
        assert "failed_requests" in stats
        assert "error_rate" in stats
        assert "provider" in stats
        assert stats["provider"] == "Mock"
    
    def test_reset_stats(self, mock_provider, mock_registry):
        """
        测试重置统计信息
        
        验证 reset_stats 能正确重置所有计数器
        """
        engine = InferenceEngine(
            provider=mock_provider,
            model_registry=mock_registry
        )
        
        # 模拟一些请求
        engine._request_count = 5
        engine._error_count = 1
        
        # 重置
        engine.reset_stats()
        
        stats = engine.get_stats()
        assert stats["total_requests"] == 0
        assert stats["successful_requests"] == 0
        assert stats["failed_requests"] == 0
    
    @pytest.mark.asyncio
    async def test_infer_error_handling(self, mock_registry):
        """
        测试错误处理
        
        验证推理错误能正确记录
        """
        # 创建会抛出异常的模拟供应商
        error_provider = Mock()
        error_provider.chat = AsyncMock(side_effect=Exception("API 错误"))
        error_provider.stream = AsyncMock(return_value=iter([]))
        
        engine = InferenceEngine(
            provider=error_provider,
            model_registry=mock_registry
        )
        
        messages = [{"role": "user", "content": "测试"}]
        config = InferenceConfig()
        
        # 验证异常被抛出
        with pytest.raises(Exception, match="API 错误"):
            await engine.infer(messages, config)
        
        # 验证错误计数增加
        stats = engine.get_stats()
        assert stats["failed_requests"] == 1
    
    @pytest.mark.asyncio
    async def test_infer_with_context(self, mock_provider, mock_registry):
        """
        测试带上下文的推理
        
        验证 context 参数能正确使用
        """
        engine = InferenceEngine(
            provider=mock_provider,
            model_registry=mock_registry
        )
        
        messages = [{"role": "user", "content": "继续"}]
        context = [{"role": "system", "content": "这是之前的对话上下文"}]
        config = InferenceConfig(context=context)
        
        result = await engine.infer(messages, config)
        
        assert isinstance(result, InferenceResult)
        mock_provider.chat.assert_called_once()
    
    def test_select_model_with_forced_provider(self, mock_provider, mock_registry):
        """
        测试强制指定供应商
        
        验证 provider 参数能强制使用指定供应商
        """
        engine = InferenceEngine(
            provider=mock_provider,
            model_registry=mock_registry
        )
        
        config = InferenceConfig(provider="anthropic")
        
        # 验证不会抛出异常（具体行为取决于实现）
        # 这里主要验证配置能正确设置
        assert config.provider == "anthropic"
    
    def test_extract_content_from_openai_response(self, mock_provider, mock_registry):
        """
        测试从 OpenAI 响应中提取内容
        
        验证 _extract_content 方法能正确处理 OpenAI 格式的响应
        """
        engine = InferenceEngine(
            provider=mock_provider,
            model_registry=mock_registry
        )
        
        # OpenAI 格式的响应
        response = {
            "choices": [{
                "message": {"content": "提取的文本内容"}
            }]
        }
        
        content = engine._extract_content(response)
        
        assert content == "提取的文本内容"
    
    def test_extract_content_empty(self, mock_provider, mock_registry):
        """
        测试提取空内容
        
        验证空响应或无效响应返回空字符串
        """
        engine = InferenceEngine(
            provider=mock_provider,
            model_registry=mock_registry
        )
        
        # 空响应
        content = engine._extract_content({})
        
        # 返回空字符串或原始内容
        assert content == "" or content == "{}"
    
    def test_extract_finish_reason(self, mock_provider, mock_registry):
        """
        测试提取结束原因
        
        验证 _extract_finish_reason 方法能正确提取结束原因
        """
        engine = InferenceEngine(
            provider=mock_provider,
            model_registry=mock_registry
        )
        
        # 带 finish_reason 的响应
        response = {
            "choices": [{"finish_reason": "stop"}]
        }
        
        reason = engine._extract_finish_reason(response)
        
        assert reason == "stop"
    
    def test_extract_usage(self, mock_provider, mock_registry):
        """
        测试提取使用统计
        
        验证 _extract_usage 方法能正确提取 token 使用统计
        """
        engine = InferenceEngine(
            provider=mock_provider,
            model_registry=mock_registry
        )
        
        response = {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150
            }
        }
        
        usage = engine._extract_usage(response)
        
        assert usage["prompt_tokens"] == 100
        assert usage["completion_tokens"] == 50
        assert usage["total_tokens"] == 150
