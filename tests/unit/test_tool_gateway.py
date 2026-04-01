"""
Tool Calling Gateway 单元测试
=============================

本模块包含 ToolCallingGateway 类的单元测试。

测试内容：
1. ToolCall 工具调用请求测试
2. ToolCallResult 工具调用结果测试
3. ToolCallingGateway 核心功能测试
4. 参数验证测试
5. OpenAI/Anthropic 格式解析测试

作者: AI Agent Team
创建时间: 2026-02-12
"""

import pytest
import pytest_asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime
from app.llm_hub.tool_gateway import (
    ToolCallingGateway,
    ToolCall,
    ToolCallResult,
    ToolCallStatus
)


class TestToolCall:
    """ToolCall 测试类"""
    
    def test_tool_call_creation(self):
        """
        测试工具调用请求创建
        
        验证 ToolCall 对象能正确初始化所有字段
        """
        tool_call = ToolCall(
            call_id="call-123",
            tool_name="search",
            arguments={"query": "天气"},
            raw_data={"id": "call-123", "type": "function"}
        )
        
        assert tool_call.call_id == "call-123"
        assert tool_call.tool_name == "search"
        assert tool_call.arguments == {"query": "天气"}
        assert tool_call.raw_data["id"] == "call-123"
    
    def test_tool_call_repr(self):
        """
        测试工具调用请求字符串表示
        
        验证 __repr__ 方法返回正确的格式
        """
        tool_call = ToolCall(
            call_id="test-call",
            tool_name="calculator",
            arguments={"expression": "2+2"},
            raw_data={}
        )
        
        repr_str = repr(tool_call)
        
        assert "ToolCall" in repr_str
        assert "test-call" in repr_str
        assert "calculator" in repr_str
    
    def test_tool_call_with_complex_arguments(self):
        """
        测试带复杂参数的工具调用
        
        验证复杂参数（嵌套字典、列表等）能正确处理
        """
        complex_args = {
            "query": "人工智能",
            "filters": {
                "date_range": {"start": "2024-01-01", "end": "2024-12-31"},
                "categories": ["tech", "science"]
            },
            "limit": 10
        }
        
        tool_call = ToolCall(
            call_id="complex-call",
            tool_name="advanced_search",
            arguments=complex_args,
            raw_data={}
        )
        
        assert tool_call.arguments["filters"]["date_range"]["start"] == "2024-01-01"
        assert tool_call.arguments["filters"]["categories"] == ["tech", "science"]


class TestToolCallResult:
    """ToolCallResult 测试类"""
    
    def test_result_success(self):
        """
        测试成功结果
        
        验证成功的工具调用能正确记录结果
        """
        result = ToolCallResult(
            call_id="call-123",
            tool_name="search",
            status=ToolCallStatus.SUCCESS,
            result={"items": ["item1", "item2"]},
            execution_time_ms=150.5
        )
        
        assert result.call_id == "call-123"
        assert result.tool_name == "search"
        assert result.status == ToolCallStatus.SUCCESS
        assert result.result == {"items": ["item1", "item2"]}
        assert result.execution_time_ms == 150.5
        assert result.error is None
    
    def test_result_failure(self):
        """
        测试失败结果
        
        验证失败的工具调用能正确记录错误信息
        """
        result = ToolCallResult(
            call_id="call-456",
            tool_name="calculator",
            status=ToolCallStatus.FAILURE,
            error="除以零错误",
            execution_time_ms=50.0
        )
        
        assert result.status == ToolCallStatus.FAILURE
        assert result.error == "除以零错误"
        assert result.result is None
    
    def test_result_not_found(self):
        """
        测试工具未找到结果
        
        验证不存在的工具调用能正确记录
        """
        result = ToolCallResult(
            call_id="call-789",
            tool_name="unknown_tool",
            status=ToolCallStatus.NOT_FOUND,
            error="Tool not found: unknown_tool"
        )
        
        assert result.status == ToolCallStatus.NOT_FOUND
        assert "unknown_tool" in result.error
    
    def test_result_validation_error(self):
        """
        测试参数验证错误结果
        
        验证参数验证失败能正确记录
        """
        result = ToolCallResult(
            call_id="call-val",
            tool_name="search",
            status=ToolCallStatus.VALIDATION_ERROR,
            error="Argument validation failed",
            execution_time_ms=10.0
        )
        
        assert result.status == ToolCallStatus.VALIDATION_ERROR
    
    def test_result_timeout(self):
        """
        测试超时结果
        
        验证超时错误能正确记录
        """
        result = ToolCallResult(
            call_id="call-timeout",
            tool_name="slow_tool",
            status=ToolCallStatus.TIMEOUT,
            error="Tool execution timed out (> 30.0s)",
            execution_time_ms=30000.0
        )
        
        assert result.status == ToolCallStatus.TIMEOUT
        assert "timed out" in result.error
    
    def test_result_to_dict_success(self):
        """
        测试成功结果转换为字典
        
        验证成功结果能正确转换为 LLM 期望的格式
        """
        result = ToolCallResult(
            call_id="call-123",
            tool_name="search",
            status=ToolCallStatus.SUCCESS,
            result={"results": ["item1", "item2"]}
        )
        
        result_dict = result.to_dict()
        
        assert result_dict["role"] == "tool"
        assert result_dict["tool_call_id"] == "call-123"
        assert result_dict["name"] == "search"
        assert "results" in result_dict["content"]

    def test_result_to_dict_success_with_datetime(self):
        """
        测试成功结果包含 datetime 时可被安全序列化

        验证 to_dict() 在工具结果含非 JSON 原生类型时不会抛异常。
        """
        result = ToolCallResult(
            call_id="call-datetime",
            tool_name="datetime",
            status=ToolCallStatus.SUCCESS,
            result={
                "success": True,
                "result": "2026-03-15T23:44:23+08:00",
                "datetime": datetime(2026, 3, 15, 23, 44, 23),
                "operation": "now"
            }
        )

        result_dict = result.to_dict()

        assert result_dict["role"] == "tool"
        assert result_dict["tool_call_id"] == "call-datetime"
        assert result_dict["name"] == "datetime"
        assert "2026-03-15" in result_dict["content"]
    
    def test_result_to_dict_failure(self):
        """
        测试失败结果转换为字典
        
        验证失败结果能正确包含错误信息
        """
        result = ToolCallResult(
            call_id="call-fail",
            tool_name="test_tool",
            status=ToolCallStatus.FAILURE,
            error="执行失败"
        )
        
        result_dict = result.to_dict()
        
        assert result_dict["role"] == "tool"
        assert "Error: 执行失败" in result_dict["content"]
    
    def test_result_repr(self):
        """
        测试结果字符串表示
        
        验证 __repr__ 方法返回正确的格式
        """
        result = ToolCallResult(
            call_id="test-call",
            tool_name="test_tool",
            status=ToolCallStatus.SUCCESS,
            execution_time_ms=100.0
        )
        
        repr_str = repr(result)
        
        assert "ToolCallResult" in repr_str
        assert "test-call" in repr_str
        assert "success" in repr_str


class TestToolCallingGateway:
    """ToolCallingGateway 测试类"""
    
    @pytest.fixture
    def mock_tool(self):
        """
        创建模拟工具
        
        返回一个模拟的工具实例
        """
        tool = Mock()
        tool.name = "test_tool"
        tool.execute = AsyncMock(return_value={"success": True})
        tool.schema = {
            "type": "object",
            "properties": {
                "param1": {"type": "string"},
                "param2": {"type": "integer"}
            },
            "required": ["param1"]
        }
        return tool
    
    def test_gateway_initialization(self):
        """
        测试网关初始化
        
        验证 ToolCallingGateway 能正确初始化
        """
        gateway = ToolCallingGateway()
        
        assert len(gateway._tools) == 0
        assert len(gateway._tool_schemas) == 0
        assert gateway._default_timeout == 30.0
        assert gateway._stats["total_calls"] == 0
    
    def test_register_tool(self, mock_tool):
        """
        测试工具注册
        
        验证工具能正确注册到网关
        """
        gateway = ToolCallingGateway()
        
        gateway.register_tool(
            name="test_tool",
            tool_instance=mock_tool,
            schema=mock_tool.schema
        )
        
        assert "test_tool" in gateway._tools
        assert "test_tool" in gateway._tool_schemas
        assert gateway.get_tool("test_tool") == mock_tool
    
    def test_unregister_tool(self, mock_tool):
        """
        测试工具注销
        
        验证工具能从网关注销
        """
        gateway = ToolCallingGateway()
        gateway.register_tool("test_tool", mock_tool, mock_tool.schema)
        
        result = gateway.unregister_tool("test_tool")
        
        assert result is True
        assert "test_tool" not in gateway._tools
        assert "test_tool" not in gateway._tool_schemas
    
    def test_unregister_nonexistent_tool(self):
        """
        测试注销不存在的工具
        
        验证注销不存在的工具返回 False
        """
        gateway = ToolCallingGateway()
        
        result = gateway.unregister_tool("nonexistent")
        
        assert result is False
    
    def test_get_available_tools(self, mock_tool):
        """
        测试获取可用工具
        
        验证能正确获取所有工具的模式列表
        """
        gateway = ToolCallingGateway()
        gateway.register_tool("test_tool", mock_tool, mock_tool.schema)
        
        tools = gateway.get_available_tools()
        
        assert len(tools) == 1
        assert tools[0]["type"] == "object"
    
    def test_set_timeout(self):
        """
        测试设置超时时间
        
        验证能正确修改默认超时时间
        """
        gateway = ToolCallingGateway()
        
        gateway.set_timeout(60.0)
        
        assert gateway._default_timeout == 60.0
    
    def test_parse_openai_tool_calls(self):
        """
        测试解析 OpenAI 格式的工具调用
        
        验证 OpenAI function calling 格式能正确解析
        """
        gateway = ToolCallingGateway()
        
        response = {
            "choices": [{
                "message": {
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "search",
                                "arguments": '{"query": "天气"}'
                            }
                        }
                    ]
                }
            }]
        }
        
        tool_calls = gateway._parse_tool_calls(response)
        
        assert len(tool_calls) == 1
        assert tool_calls[0].call_id == "call-1"
        assert tool_calls[0].tool_name == "search"
        assert tool_calls[0].arguments == {"query": "天气"}
    
    def test_parse_anthropic_tool_calls(self):
        """
        测试解析 Anthropic 格式的工具调用
        
        验证 Anthropic tool use 格式能正确解析
        """
        gateway = ToolCallingGateway()
        
        response = {
            "content": [
                {
                    "type": "tool_use",
                    "id": "call-2",
                    "name": "calculate",
                    "input": {"expression": "2+2"}
                }
            ]
        }
        
        tool_calls = gateway._parse_tool_calls(response)
        
        assert len(tool_calls) == 1
        assert tool_calls[0].call_id == "call-2"
        assert tool_calls[0].tool_name == "calculate"
        assert tool_calls[0].arguments == {"expression": "2+2"}
    
    def test_parse_empty_calls(self):
        """
        测试解析空工具调用
        
        验证没有工具调用时返回空列表
        """
        gateway = ToolCallingGateway()
        
        # 无 tool_calls 的响应
        response1 = {"choices": [{"message": {}}]}
        # 无 content 的响应
        response2 = {}
        
        assert gateway._parse_tool_calls(response1) == []
        assert gateway._parse_tool_calls(response2) == []
    
    def test_parse_arguments_json(self):
        """
        测试解析 JSON 格式参数
        
        验证 JSON 格式的参数能正确解析
        """
        gateway = ToolCallingGateway()
        
        args_str = '{"query": "测试", "limit": 10}'
        result = gateway._parse_arguments(args_str)
        
        assert result == {"query": "测试", "limit": 10}
    
    def test_parse_arguments_invalid_json(self):
        """
        测试解析无效 JSON 参数
        
        验证无效 JSON 返回空字典
        """
        gateway = ToolCallingGateway()
        
        result = gateway._parse_arguments("无效的 JSON")
        
        assert result == {}

    def test_parse_arguments_python_executor_recover_code(self):
        """
        测试 python_executor 参数容错恢复

        场景：
        - LLM 返回的 arguments 不是严格 JSON（字符串被截断/转义不完整）
        - 网关仍可提取 code 字段，避免直接走“缺少必需参数”分支
        """
        gateway = ToolCallingGateway()

        malformed = '{"code": "print(\\"hello\\")\\nfor i in range(3):\\n    print(i)'
        result = gateway._parse_arguments(malformed, tool_name="python_executor")

        assert isinstance(result, dict)
        assert "code" in result
        assert "print" in result["code"]
    
    def test_validate_arguments_success(self):
        """
        测试参数验证成功
        
        验证有效参数能通过验证
        """
        gateway = ToolCallingGateway()
        
        schema = {
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"}
            }
        }
        
        args = {"query": "测试", "limit": 10}
        result = gateway._validate_arguments("search", args, schema)
        
        assert result == args
    
    def test_validate_arguments_missing_required(self):
        """
        测试缺少必需参数
        
        验证缺少必需参数时返回 None
        """
        gateway = ToolCallingGateway()
        
        schema = {
            "required": ["query"],
            "properties": {
                "query": {"type": "string"}
            }
        }
        
        args = {"limit": 10}  # 缺少 query
        result = gateway._validate_arguments("search", args, schema)
        
        assert result is None
    
    def test_validate_arguments_type_error(self):
        """
        测试参数类型错误
        
        验证类型不匹配时返回 None
        """
        gateway = ToolCallingGateway()
        
        schema = {
            "required": ["count"],
            "properties": {
                "count": {"type": "integer"}
            }
        }
        
        args = {"count": "应该是数字"}  # 类型错误
        result = gateway._validate_arguments("test", args, schema)
        
        assert result is None
    
    def test_check_type(self):
        """
        测试类型检查
        
        验证各种类型的检查结果正确
        """
        gateway = ToolCallingGateway()
        
        assert gateway._check_type("hello", "string") is True
        assert gateway._check_type(123, "integer") is True
        assert gateway._check_type(1.5, "number") is True
        assert gateway._check_type(True, "boolean") is True
        assert gateway._check_type([1, 2], "array") is True
        assert gateway._check_type({"key": "value"}, "object") is True
        assert gateway._check_type("123", "integer") is False  # string 不是 integer
    
    @pytest.mark.asyncio
    async def test_execute_tool_calls_success(self, mock_tool):
        """
        测试成功执行工具调用
        
        验证工具能正确执行并返回结果
        """
        gateway = ToolCallingGateway()
        gateway.register_tool("test_tool", mock_tool, mock_tool.schema)
        
        response = {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "test_tool",
                            "arguments": '{"param1": "value1"}'
                        }
                    }]
                }
            }]
        }
        
        results = await gateway.execute_tool_calls(response)
        
        assert len(results) == 1
        assert results[0].status == ToolCallStatus.SUCCESS
        assert results[0].result == {"success": True}
        mock_tool.execute.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_execute_tool_calls_not_found(self):
        """
        测试工具未找到
        
        验证不存在的工具调用返回 NOT_FOUND 状态
        """
        gateway = ToolCallingGateway()
        
        response = {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "id": "call-unknown",
                        "type": "function",
                        "function": {
                            "name": "nonexistent_tool",
                            "arguments": "{}"
                        }
                    }]
                }
            }]
        }
        
        results = await gateway.execute_tool_calls(response)
        
        assert len(results) == 1
        assert results[0].status == ToolCallStatus.NOT_FOUND
        assert "nonexistent_tool" in results[0].error

    @pytest.mark.asyncio
    async def test_execute_tool_calls_should_reject_tool_outside_allowed_context(self, mock_tool):
        """
        测试运行时白名单拦截

        验证即使工具已注册，只要不在本次允许执行的 allowed_tool_names 中，
        ToolCallingGateway 也必须在公共层直接拒绝执行。
        """
        gateway = ToolCallingGateway()
        gateway.register_tool("test_tool", mock_tool, mock_tool.schema)

        response = {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "id": "call-forbidden",
                        "type": "function",
                        "function": {
                            "name": "test_tool",
                            "arguments": '{"param1": "value1"}'
                        }
                    }]
                }
            }]
        }

        results = await gateway.execute_tool_calls(
            response,
            context={"allowed_tool_names": ["other_tool"]},
        )

        assert len(results) == 1
        assert results[0].status == ToolCallStatus.FORBIDDEN
        assert "not allowed" in results[0].error
        mock_tool.execute.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_execute_multiple_tool_calls(self, mock_tool):
        """
        测试执行多个工具调用
        
        验证多个工具调用能按顺序执行
        """
        gateway = ToolCallingGateway()
        gateway.register_tool("test_tool", mock_tool, mock_tool.schema)
        
        response = {
            "choices": [{
                "message": {
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "test_tool",
                                "arguments": '{"param1": "value1"}'
                            }
                        },
                        {
                            "id": "call-2",
                            "type": "function",
                            "function": {
                                "name": "test_tool",
                                "arguments": '{"param1": "value2"}'
                            }
                        }
                    ]
                }
            }]
        }
        
        results = await gateway.execute_tool_calls(response)
        
        assert len(results) == 2
        assert results[0].call_id == "call-1"
        assert results[1].call_id == "call-2"
        assert mock_tool.execute.call_count == 2
    
    @pytest.mark.asyncio
    async def test_execute_tool_calls_empty(self):
        """
        测试执行空工具调用
        
        验证没有工具调用时返回空列表
        """
        gateway = ToolCallingGateway()
        
        response = {"choices": [{"message": {}}]}
        
        results = await gateway.execute_tool_calls(response)
        
        assert results == []
    
    def test_format_results_for_llm(self):
        """
        测试格式化结果给 LLM
        
        验证结果能正确转换为 LLM 期望的格式
        """
        gateway = ToolCallingGateway()
        
        success_result = ToolCallResult(
            call_id="call-1",
            tool_name="search",
            status=ToolCallStatus.SUCCESS,
            result={"items": ["a", "b"]}
        )
        failure_result = ToolCallResult(
            call_id="call-2",
            tool_name="test",
            status=ToolCallStatus.FAILURE,
            error="执行失败"
        )
        
        formatted = gateway.format_results_for_llm([success_result, failure_result])
        
        assert len(formatted) == 2
        assert formatted[0]["role"] == "tool"
        assert "items" in formatted[0]["content"]
        assert formatted[1]["role"] == "tool"
        assert "Error" in formatted[1]["content"]
    
    def test_get_stats(self):
        """
        测试获取统计信息
        
        验证统计信息正确反映调用情况
        """
        gateway = ToolCallingGateway()
        
        # 模拟一些调用
        gateway._stats["total_calls"] = 10
        gateway._stats["successful_calls"] = 8
        gateway._stats["failed_calls"] = 2
        
        stats = gateway.get_stats()
        
        assert stats["total_calls"] == 10
        assert stats["successful_calls"] == 8
        assert stats["failed_calls"] == 2
        assert stats["success_rate"] == 0.8
        assert "available_tools" in stats
    
    def test_reset_stats(self):
        """
        测试重置统计信息
        
        验证统计信息能正确重置
        """
        gateway = ToolCallingGateway()
        
        gateway._stats["total_calls"] = 100
        gateway._call_history.append(Mock())  # 添加假历史记录
        
        gateway.reset_stats()
        
        assert gateway._stats["total_calls"] == 0
        assert gateway._stats["successful_calls"] == 0
        assert gateway._stats["failed_calls"] == 0
        assert len(gateway._call_history) == 0
