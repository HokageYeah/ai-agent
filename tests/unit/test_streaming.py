"""
Streaming Manager 单元测试
==========================

本模块包含 StreamingManager 类的单元测试。

测试内容：
1. StreamChunk 流式块测试
2. StreamingManager 核心功能测试
3. 不同供应商格式解析测试
4. 内容过滤器测试
5. Token 计数测试

作者: AI Agent Team
创建时间: 2026-02-12
"""

import pytest
import pytest_asyncio
from unittest.mock import Mock, AsyncMock
from app.llm_hub.streaming import StreamingManager, StreamChunk


class TestStreamChunk:
    """StreamChunk 测试类"""
    
    def test_chunk_creation(self):
        """
        测试流式块创建
        
        验证 StreamChunk 对象能正确初始化所有字段
        """
        chunk = StreamChunk(
            content="你好",
            delta="你好",
            is_end=False,
            chunk_id="chunk-1",
            role="assistant"
        )
        
        assert chunk.content == "你好"
        assert chunk.delta == "你好"
        assert chunk.is_end is False
        assert chunk.chunk_id == "chunk-1"
        assert chunk.role == "assistant"
        assert chunk.usage is None
    
    def test_chunk_with_usage(self):
        """
        测试带使用统计的流式块
        
        验证包含 usage 的块能正确处理
        """
        usage = {
            "prompt_tokens": 10,
            "completion_tokens": 5
        }
        
        chunk = StreamChunk(
            content="完整回复",
            delta="",
            is_end=True,
            chunk_id="final-chunk",
            usage=usage
        )
        
        assert chunk.is_end is True
        assert chunk.usage["prompt_tokens"] == 10
        assert chunk.usage["completion_tokens"] == 5
    
    def test_chunk_repr(self):
        """
        测试流式块字符串表示
        
        验证 __repr__ 方法返回正确的格式
        """
        chunk = StreamChunk(
            content="这是一个很长的回复内容",
            delta="...",
            is_end=False,
            chunk_id="test-chunk"
        )
        
        repr_str = repr(chunk)
        
        assert "StreamChunk" in repr_str
        # 验证截取的前50个字符在 repr 中
        assert "..." in repr_str or "这是一个" in repr_str
    
    def test_chunk_default_values(self):
        """
        测试流式块默认值
        
        验证未指定的字段使用默认值
        """
        chunk = StreamChunk()
        
        assert chunk.content == ""
        assert chunk.delta == ""
        assert chunk.is_end is False
        assert chunk.chunk_id == ""
        assert chunk.role == "assistant"
        assert chunk.usage is None
    
    def test_chunk_accumulation(self):
        """
        测试流式块内容累积
        
        验证多个块的内容累积逻辑
        """
        # 模拟累积过程
        accumulated = ""
        
        chunks_data = [
            {"delta": "今天", "is_end": False},
            {"delta": "天气", "is_end": False},
            {"delta": "很好", "is_end": True}
        ]
        
        for i, data in enumerate(chunks_data):
            accumulated += data["delta"]
            is_final = data["is_end"]
            
            # 创建块
            chunk = StreamChunk(
                content=accumulated,
                delta=data["delta"],
                is_end=is_final,
                chunk_id=f"chunk-{i}"
            )
            
            assert chunk.content == accumulated
        
        assert accumulated == "今天天气很好"


class TestStreamingManager:
    """StreamingManager 测试类"""
    
    def setup_method(self):
        """
        每个测试方法执行前的清理工作
        """
        # 每个测试使用新的 manager，不需要额外清理
    
    def test_manager_initialization(self):
        """
        测试管理器初始化
        
        验证 StreamingManager 能正确初始化
        """
        manager = StreamingManager()
        
        assert len(manager._content_filters) == 0
        assert manager._total_tokens == 0
    
    def test_add_content_filter(self):
        """
        测试添加内容过滤器
        
        验证过滤器能正确添加到管理器
        """
        manager = StreamingManager()
        
        def my_filter(content):
            return content.upper()
        
        manager.add_content_filter(my_filter)
        
        assert len(manager._content_filters) == 1
        assert manager._content_filters[0] == my_filter
    
    def test_add_multiple_filters(self):
        """
        测试添加多个过滤器
        
        验证多个过滤器能正确添加
        """
        manager = StreamingManager()
        
        filter1 = lambda c: c.replace("a", "A")
        filter2 = lambda c: c.replace("b", "B")
        filter3 = lambda c: c.upper()
        
        manager.add_content_filter(filter1)
        manager.add_content_filter(filter2)
        manager.add_content_filter(filter3)
        
        assert len(manager._content_filters) == 3
    
    def test_remove_content_filter(self):
        """
        测试移除内容过滤器
        
        验证过滤器能从管理器移除
        """
        manager = StreamingManager()
        
        def my_filter(content):
            return content.upper()
        
        manager.add_content_filter(my_filter)
        assert len(manager._content_filters) == 1
        
        manager.remove_content_filter(my_filter)
        assert len(manager._content_filters) == 0
    
    def test_remove_nonexistent_filter(self):
        """
        测试移除不存在的过滤器
        
        验证移除不存在的过滤器不会报错
        """
        manager = StreamingManager()
        
        def filter1(content):
            return content
        def filter2(content):
            return content
        
        manager.add_content_filter(filter1)
        # 尝试移除不同的函数
        manager.remove_content_filter(filter2)
        
        # filter1 应该还在
        assert len(manager._content_filters) == 1
    
    def test_apply_filters(self):
        """
        测试应用过滤器
        
        验证所有过滤器按顺序应用
        """
        manager = StreamingManager()
        
        # 添加过滤器
        manager.add_content_filter(lambda c: c.replace("a", "X"))
        manager.add_content_filter(lambda c: c.replace("b", "Y"))
        manager.add_content_filter(lambda c: c.upper())
        
        result = manager._apply_filters("abc")
        
        assert result == "XYC"  # a->X, b->Y, 上大写
    
    def test_apply_no_filters(self):
        """
        测试无过滤器时的应用
        
        验证没有过滤器时内容不变
        """
        manager = StreamingManager()
        
        result = manager._apply_filters("原始内容")
        
        assert result == "原始内容"
    
    def test_parse_openai_chunk(self):
        """
        测试解析 OpenAI 流式块
        
        验证 OpenAI 格式的流式响应能正确解析
        """
        manager = StreamingManager()
        
        # OpenAI 普通内容块
        openai_chunk = {
            "id": "test-id",
            "object": "chat.completion.chunk",
            "choices": [{
                "delta": {"content": "你好"},
                "finish_reason": None
            }]
        }
        
        result = manager._parse_provider_chunk("openai", openai_chunk)
        
        assert result is not None
        assert result.delta == "你好"
        assert result.is_end is False
        assert result.chunk_id == "test-id"
    
    def test_parse_openai_final_chunk(self):
        """
        测试解析 OpenAI 结束块
        
        验证 OpenAI 结束块（带 finish_reason）能正确解析
        """
        manager = StreamingManager()
        
        openai_chunk = {
            "id": "test-id",
            "choices": [{
                "delta": {"content": ""},
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5
            }
        }
        
        result = manager._parse_provider_chunk("openai", openai_chunk)
        
        assert result.is_end is True
        assert result.usage is not None
        assert result.usage["prompt_tokens"] == 10
    
    def test_parse_anthropic_message_start(self):
        """
        测试解析 Anthropic 消息开始块
        
        验证 Anthropic message_start 事件能正确解析
        """
        manager = StreamingManager()
        
        anthropic_chunk = {
            "type": "message_start",
            "message": {
                "id": "msg-123",
                "type": "message"
            }
        }
        
        result = manager._parse_provider_chunk("anthropic", anthropic_chunk)
        
        assert result is not None
        assert result.chunk_id == "msg-123"
        assert result.is_end is False
    
    def test_parse_anthropic_content_delta(self):
        """
        测试解析 Anthropic 内容增量块
        
        验证 Anthropic content_block_delta 事件能正确解析
        """
        manager = StreamingManager()
        
        anthropic_chunk = {
            "type": "content_block_delta",
            "id": "msg-123",
            "delta": {
                "type": "text_delta",
                "text": "这是增量文本"
            }
        }
        
        result = manager._parse_provider_chunk("anthropic", anthropic_chunk)
        
        assert result is not None
        assert result.delta == "这是增量文本"
        assert result.is_end is False
    
    def test_parse_anthropic_message_delta(self):
        """
        测试解析 Anthropic 消息增量块
        
        验证 Anthropic message_delta 事件（包含 usage）能正确解析
        """
        manager = StreamingManager()
        
        anthropic_chunk = {
            "type": "message_delta",
            "usage": {
                "input_tokens": 15,
                "output_tokens": 10
            }
        }
        
        result = manager._parse_provider_chunk("anthropic", anthropic_chunk)
        
        assert result.is_end is True
        assert result.usage["input_tokens"] == 15
    
    def test_parse_anthropic_message_stop(self):
        """
        测试解析 Anthropic 消息结束块
        
        验证 Anthropic message_stop 事件能正确解析
        """
        manager = StreamingManager()
        
        anthropic_chunk = {
            "type": "message_stop"
        }
        
        result = manager._parse_provider_chunk("anthropic", anthropic_chunk)
        
        assert result is not None
        assert result.is_end is True
    
    def test_parse_anthropic_unknown_event(self):
        """
        测试解析 Anthropic 未知事件
        
        验证未知事件类型返回 None
        """
        manager = StreamingManager()
        
        anthropic_chunk = {
            "type": "unknown_event"
        }
        
        result = manager._parse_provider_chunk("anthropic", anthropic_chunk)
        
        assert result is None
    
    def test_parse_unknown_provider(self):
        """
        测试解析未知供应商
        
        验证未知供应商使用通用格式
        """
        manager = StreamingManager()
        
        unknown_chunk = {"content": "测试"}
        
        result = manager._parse_provider_chunk("unknown", unknown_chunk)
        
        assert result is not None
        assert result.delta == str(unknown_chunk)
    
    @pytest.mark.asyncio
    async def test_stream_response_empty(self):
        """
        测试空流式响应
        
        验证空流式响应能正确处理
        """
        manager = StreamingManager()
        
        # 创建空的异步迭代器
        async def empty_stream():
            return
            yield  # 确保是生成器
        
        chunks = []
        async for chunk in manager.stream_response("openai", empty_stream()):
            chunks.append(chunk)
        
        # 应该只有最后的结束块
        assert len(chunks) == 1
        assert chunks[0].is_end is True
        assert chunks[0].content == ""
    
    @pytest.mark.asyncio
    async def test_stream_response_openai(self):
        """
        测试 OpenAI 流式响应
        
        验证 OpenAI 格式的流式响应能正确处理
        """
        manager = StreamingManager()
        
        # 模拟 OpenAI 流式响应
        async def mock_openai_stream():
            chunks_data = [
                {"id": "resp-1", "content": "你", "finish_reason": None},
                {"id": "resp-1", "content": "好", "finish_reason": None},
                {"id": "resp-1", "content": "！", "finish_reason": "stop"}
            ]
            
            for data in chunks_data:
                yield {
                    "id": data["id"],
                    "choices": [{
                        "delta": {"content": data["content"]},
                        "finish_reason": data["finish_reason"]
                    }]
                }
        
        chunks = []
        async for chunk in manager.stream_response("openai", mock_openai_stream()):
            chunks.append(chunk)
        
        print('chunks:', chunks)
        # 验证结果：3个数据块 + 1个最终聚合块 = 4个块
        assert len(chunks) == 4
        
        # 前两个块不是结束块
        assert chunks[0].is_end is False
        assert chunks[0].delta == "你"
        assert chunks[1].delta == "好"
        
        # 第三个数据块是结束块
        assert chunks[2].is_end is True
        assert chunks[2].delta == "！"
        
        # 第四个是最终聚合块，包含完整内容
        assert chunks[3].is_end is True
        assert chunks[3].content == "你好！"
        assert chunks[3].delta == ""
    
    @pytest.mark.asyncio
    async def test_stream_response_with_filters(self):
        """
        测试带过滤器的流式响应
        
        验证内容过滤器在流式处理中正确应用
        """
        manager = StreamingManager()
        
        # 添加过滤器：替换特定词
        manager.add_content_filter(lambda c: c.replace("敏感词", "***"))
        
        async def mock_stream():
            yield {
                "id": "test",
                "choices": [{"delta": {"content": "这是包含敏感词的内容"}, "finish_reason": None}]
            }
            yield {
                "id": "test",
                "choices": [{"delta": {"content": "，正常内容"}, "finish_reason": "stop"}]
            }
        
        # 收集累积内容
        accumulated = ""
        async for chunk in manager.stream_response("openai", mock_stream()):
            accumulated += chunk.delta
        
        # 验证过滤器应用
        assert "敏感词" not in accumulated
        assert "***" in accumulated
    
    @pytest.mark.asyncio
    async def test_stream_response_error_handling(self):
        """
        测试流式响应错误处理
        
        验证流式处理中的错误能正确处理
        """
        manager = StreamingManager()
        
        # 创建会抛出异常的流
        async def error_stream():
            yield {"id": "test", "choices": [{"delta": {"content": "部分内容"}, "finish_reason": None}]}
            raise Exception("流式处理错误")
        
        # 应该能捕获异常
        with pytest.raises(Exception, match="流式处理错误"):
            async for chunk in manager.stream_response("openai", error_stream()):
                pass
    
    def test_create_openai_compatible_stream(self):
        """
        测试创建 OpenAI 兼容流
        
        验证能创建用于测试的模拟流
        """
        manager = StreamingManager()
        
        chunks = [
            {"id": "test", "choices": [{"delta": {"content": "第1块"}}]},
            {"id": "test", "choices": [{"delta": {"content": "第2块"}}]},
        ]
        
        stream = manager.create_openai_compatible_stream(chunks)
        
        # 验证流的内容
        result_list = list(stream)
        assert len(result_list) == 2
        assert result_list[0]["choices"][0]["delta"]["content"] == "第1块"
    
    def test_reset_token_count(self):
        """
        测试重置 Token 计数
        
        验证 Token 计数能正确重置
        """
        manager = StreamingManager()
        
        manager._total_tokens = 1000
        manager.reset_token_count()
        
        assert manager._total_tokens == 0
    
    def test_create_streaming_manager(self):
        """
        测试创建 StreamingManager 便捷函数
        
        验证便捷函数能正确创建实例
        """
        manager = create_streaming_manager()
        
        assert isinstance(manager, StreamingManager)
        assert len(manager._content_filters) == 0
        assert manager._total_tokens == 0


# =============================================================================
# 便捷函数
# =============================================================================

def create_streaming_manager() -> StreamingManager:
    """
    创建流式管理器实例的便捷函数
    
    Returns:
        新的 StreamingManager 实例
    """
    return StreamingManager()


# =============================================================================
# 测试辅助函数
# =============================================================================

def create_openai_chunk(
    chunk_id: str,
    content: str,
    is_end: bool = False,
    usage: dict = None
) -> dict:
    """
    创建 OpenAI 格式的测试块
    
    Args:
        chunk_id: 块 ID
        content: 增量内容
        is_end: 是否结束
        usage: 使用统计
    
    Returns:
        OpenAI 格式的块字典
    """
    return {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "choices": [{
            "delta": {"content": content},
            "finish_reason": "stop" if is_end else None
        }],
        "usage": usage
    }


def create_anthropic_chunk(
    event_type: str,
    chunk_id: str = None,
    content: str = None,
    usage: dict = None
) -> dict:
    """
    创建 Anthropic 格式的测试块
    
    Args:
        event_type: 事件类型
        chunk_id: 消息 ID
        content: 文本内容
        usage: 使用统计
    
    Returns:
        Anthropic 格式的块字典
    """
    chunk = {"type": event_type}
    
    if chunk_id:
        chunk["id"] = chunk_id
    
    if event_type == "content_block_delta" and content:
        chunk["delta"] = {
            "type": "text_delta",
            "text": content
        }
    
    if usage:
        chunk["usage"] = usage
    
    return chunk
