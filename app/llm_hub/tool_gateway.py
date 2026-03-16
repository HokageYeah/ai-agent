"""
工具调用网关 (Tool Calling Gateway)
====================================

本模块负责处理 LLM 的工具调用请求，统一不同供应商的工具调用格式。

功能特点：
1. 解析 LLM 的工具调用请求
2. 参数验证和类型转换
3. 执行工具调用并返回结果
4. 支持 OpenAI function calling 格式
5. 支持 Anthropic tool use 格式

作者: AI Agent Team
创建时间: 2026-02-12
"""

import ast
import json
import asyncio
from typing import Dict, List, Any, Optional, Callable
from pydantic import ValidationError
from loguru import logger
from colorama import Fore, Style, Back
from datetime import datetime
from enum import Enum


class ToolCallStatus(Enum):
    """工具调用状态"""
    SUCCESS = "success"
    FAILURE = "failure"
    NOT_FOUND = "not_found"
    VALIDATION_ERROR = "validation_error"
    TIMEOUT = "timeout"


class ToolCall:
    """
    工具调用请求
    
    统一不同供应商的工具调用格式
    """
    
    def __init__(
        self,
        call_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        raw_data: Dict[str, Any]
    ):
        """
        初始化工具调用请求
        
        Args:
            call_id: 调用 ID
            tool_name: 工具名称
            arguments: 工具参数
            raw_data: 原始数据（用于调试）
        """
        self.call_id = call_id
        self.tool_name = tool_name
        self.arguments = arguments
        self.raw_data = raw_data
    
    def __repr__(self) -> str:
        """返回调用请求的字符串表示"""
        return (
            f"ToolCall(call_id={self.call_id}, "
            f"tool_name={self.tool_name}, "
            f"args={self.arguments})"
        )


class ToolCallResult:
    """
    工具调用结果
    """
    
    def __init__(
        self,
        call_id: str,
        tool_name: str,
        status: ToolCallStatus,
        result: Any = None,
        error: Optional[str] = None,
        execution_time_ms: float = 0.0
    ):
        """
        初始化工具调用结果
        
        Args:
            call_id: 调用 ID
            tool_name: 工具名称
            status: 调用状态
            result: 执行结果
            error: 错误信息
            execution_time_ms: 执行时间（毫秒）
        """
        self.call_id = call_id
        self.tool_name = tool_name
        self.status = status
        self.result = result
        self.error = error
        self.execution_time_ms = execution_time_ms
        self.timestamp = datetime.now()
    
    def __repr__(self) -> str:
        """返回结果的字符串表示"""
        return (
            f"ToolCallResult(call_id={self.call_id}, "
            f"tool_name={self.tool_name}, "
            f"status={self.status.value}, "
            f"time={self.execution_time_ms:.2f}ms)"
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典格式（用于返回给 LLM）
        
        Returns:
            字典格式的结果
        """
        if self.status == ToolCallStatus.SUCCESS:
            return {
                "role": "tool",
                "tool_call_id": self.call_id,
                "name": self.tool_name,
                # 关键兜底：工具结果里可能包含 datetime/date/time 等对象。
                # 若不加 default=str，会在工具调用循环里直接抛出
                # "Object of type datetime is not JSON serializable" 并中断主流程。
                "content": json.dumps(self.result, ensure_ascii=False, default=str)
            }
        else:
            return {
                "role": "tool",
                "tool_call_id": self.call_id,
                "name": self.tool_name,
                "content": f"Error: {self.error}"
            }


class ToolCallingGateway:
    """
    工具调用网关
    
    负责：
    1. 解析 LLM 的工具调用请求（OpenAI/Anthropic 格式）
    2. 参数验证
    3. 执行工具调用
    4. 返回结果
    """
    
    def __init__(self):
        """
        初始化工具调用网关
        """
        # 工具注册表: name -> tool_instance
        self._tools: Dict[str, Any] = {}
        
        # 工具模式注册表: name -> schema
        self._tool_schemas: Dict[str, Dict[str, Any]] = {}
        
        # 执行超时时间（秒）
        self._default_timeout = 300.0
        
        # 调用历史
        self._call_history: List[ToolCallResult] = []
        
        # 统计信息
        self._stats = {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0
        }
        
        logger.info(f"{Fore.CYAN}初始化工具调用网关 (ToolCallingGateway){Style.RESET_ALL}")
    
    def register_tool(self, name: str, tool_instance: Any, schema: Dict[str, Any]) -> None:
        """
        注册工具
        
        Args:
            name: 工具名称
            tool_instance: 工具实例
            schema: 工具参数模式 (JSON Schema)
        """
        self._tools[name] = tool_instance
        self._tool_schemas[name] = schema
        
        logger.info(
            f"{Fore.GREEN}注册工具: {name}, 参数模式: {list(schema.get('properties', {}).keys())}{Style.RESET_ALL}"
        )
    
    def unregister_tool(self, name: str) -> bool:
        """
        注销工具
        
        Args:
            name: 工具名称
            
        Returns:
            是否成功注销
        """
        if name in self._tools:
            del self._tools[name]
            del self._tool_schemas[name]
            logger.info(f"{Fore.CYAN}注销工具: {name}{Style.RESET_ALL}")
            return True
        return False
    
    def get_tool(self, name: str) -> Optional[Any]:
        """
        获取工具实例
        
        Args:
            name: 工具名称
            
        Returns:
            工具实例，如果不存在返回 None
        """
        return self._tools.get(name)
    
    def get_available_tools(self) -> List[Dict[str, Any]]:
        """
        获取所有可用工具的模式列表
        
        Returns:
            工具模式列表（用于传递给 LLM）
        """
        return list(self._tool_schemas.values())
    
    def set_timeout(self, timeout_seconds: float) -> None:
        """
        设置默认超时时间
        
        Args:
            timeout_seconds: 超时时间（秒）
        """
        self._default_timeout = timeout_seconds
        logger.debug(f"{Fore.BLUE}设置工具调用超时时间: {timeout_seconds}秒{Style.RESET_ALL}")
    
    async def execute_tool_calls(
        self,
        llm_response: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> List[ToolCallResult]:
        """
        执行 LLM 请求的工具调用
        
        Args:
            llm_response: LLM 的响应
            context: 额外上下文信息
            
        Returns:
            工具调用结果列表
        """
        context = context or {}
        
        logger.info(f"{Fore.BLUE}开始执行工具调用{Style.RESET_ALL}")
        
        # 步骤 1: 解析工具调用请求
        tool_calls = self._parse_tool_calls(llm_response)
        
        if not tool_calls:
            logger.debug(f"{Fore.BLUE}没有检测到工具调用请求{Style.RESET_ALL}")
            return []
        
        logger.info(
            f"{Fore.BLUE}检测到 {len(tool_calls)} 个工具调用请求{Style.RESET_ALL}"
        )

        # 批次统计（本次 execute_tool_calls 调用）
        batch_total = 0
        batch_success = 0
        batch_failed = 0

        # 步骤 2: 执行每个工具调用
        results = []
        for tool_call in tool_calls:
            result = await self._execute_single_call(tool_call, context)
            results.append(result)

            # 更新本次批次统计
            batch_total += 1
            if result.status == ToolCallStatus.SUCCESS:
                batch_success += 1
            else:
                batch_failed += 1

            # 更新统计
            self._stats["total_calls"] += 1
            if result.status == ToolCallStatus.SUCCESS:
                self._stats["successful_calls"] += 1
            else:
                self._stats["failed_calls"] += 1
        
        # 记录到历史
        self._call_history.extend(results)
        
        # 只保留最近 100 条记录
        if len(self._call_history) > 100:
            self._call_history = self._call_history[-100:]

        # 打印统计
        # NOTE:
        # - “本次”统计用于描述当前这一次 execute_tool_calls 的执行结果
        # - “累计”统计用于全局观测网关生命周期内的总调用情况
        # 这样可避免日志里出现“检测到 1 个请求，但总数=10”的理解歧义。
        batch_success_rate = batch_success / max(1, batch_total)
        cumulative_success_rate = self._stats["successful_calls"] / max(1, self._stats["total_calls"])
        logger.info(
            f"{Fore.GREEN}工具调用完成: "
            f"本次总数={batch_total}, "
            f"本次成功={batch_success}, "
            f"本次失败={batch_failed}, "
            f"本次成功率={batch_success_rate:.1%} | "
            f"累计总数={self._stats['total_calls']}, "
            f"累计成功={self._stats['successful_calls']}, "
            f"累计失败={self._stats['failed_calls']}, "
            f"累计成功率={cumulative_success_rate:.1%}{Style.RESET_ALL}"
        )
        
        return results
    
    def _parse_tool_calls(self, llm_response: Dict[str, Any]) -> List[ToolCall]:
        """
        解析 LLM 响应中的工具调用请求
        
        支持 OpenAI 和 Anthropic 两种格式
        
        Args:
            llm_response: LLM 响应
            
        Returns:
            工具调用请求列表
        """
        tool_calls = []
        
        # OpenAI 格式: {"choices": [{"message": {"tool_calls": [...]}}]}
        if "choices" in llm_response:
            choice = llm_response["choices"][0]
            message = choice.get("message", {})
            openai_calls = message.get("tool_calls", [])
            
            for call in openai_calls:
                tool_name = call.get("function", {}).get("name", "")
                tool_call = ToolCall(
                    call_id=call.get("id", ""),
                    tool_name=tool_name,
                    arguments=self._parse_arguments(
                        call.get("function", {}).get("arguments", "{}"),
                        tool_name=tool_name,
                    ),
                    raw_data=call
                )
                tool_calls.append(tool_call)
        
        # Anthropic 格式: {"content": [{"type": "tool_use", ...}]}
        elif "content" in llm_response:
            for block in llm_response["content"]:
                if block.get("type") == "tool_use":
                    tool_call = ToolCall(
                        call_id=block.get("id", ""),
                        tool_name=block.get("name", ""),
                        arguments=block.get("input", {}),
                        raw_data=block
                    )
                    tool_calls.append(tool_call)
        
        return tool_calls
    
    def _parse_arguments(self, arguments_str: Any, tool_name: str = "") -> Dict[str, Any]:
        """
        解析参数字符串
        
        Args:
            arguments_str: JSON 格式的参数字符串
            tool_name: 工具名称（用于做工具特定容错）
            
        Returns:
            解析后的参数字典
        """
        if isinstance(arguments_str, dict):
            return arguments_str
        if arguments_str is None:
            return {}

        if not isinstance(arguments_str, str):
            arguments_str = str(arguments_str)

        raw_text = arguments_str.strip()
        if not raw_text:
            return {}

        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            # 兜底1：尝试使用 Python 字面量解析（部分模型会返回单引号风格 dict）
            try:
                parsed = ast.literal_eval(raw_text)
                if isinstance(parsed, dict):
                    logger.warning(
                        f"{Fore.YELLOW}工具参数 JSON 解析失败，已通过 literal_eval 容错恢复: "
                        f"tool={tool_name or 'unknown'}{Style.RESET_ALL}"
                    )
                    return parsed
            except Exception:
                pass

            # 兜底2：针对 python_executor 的 code 参数做宽松提取
            if tool_name == "python_executor":
                recovered = self._recover_python_executor_args(raw_text)
                if recovered is not None:
                    logger.warning(
                        f"{Fore.YELLOW}python_executor 参数 JSON 解析失败，"
                        f"已通过宽松提取恢复 code 字段{Style.RESET_ALL}"
                    )
                    return recovered

            logger.warning(
                f"{Fore.YELLOW}无法解析工具参数: tool={tool_name or 'unknown'}, "
                f"error={exc}, payload={raw_text[:120]}...{Style.RESET_ALL}"
            )
            return {}

    def _recover_python_executor_args(self, raw_text: str) -> Optional[Dict[str, Any]]:
        """
        从格式损坏的参数文本中恢复 python_executor 的 code 字段。

        典型场景：
        - LLM 生成了超长 tool arguments，字符串转义不完整导致 json.loads 失败；
        - 但 payload 里仍包含 `"code": "..."` 片段，提取后可继续执行。
        """
        if not raw_text:
            return None

        # 情况1：模型只回了纯代码字符串（没有包裹 JSON 对象）
        if not raw_text.lstrip().startswith("{"):
            return {"code": raw_text}

        marker = '"code"'
        marker_idx = raw_text.find(marker)
        if marker_idx < 0:
            return None

        colon_idx = raw_text.find(":", marker_idx + len(marker))
        if colon_idx < 0:
            return None

        i = colon_idx + 1
        while i < len(raw_text) and raw_text[i].isspace():
            i += 1
        if i >= len(raw_text):
            return None

        quote = raw_text[i]
        if quote not in ('"', "'"):
            return None
        i += 1

        chars: List[str] = []
        escaped = False
        while i < len(raw_text):
            ch = raw_text[i]
            if escaped:
                chars.append(ch)
                escaped = False
                i += 1
                continue
            if ch == "\\":
                chars.append(ch)
                escaped = True
                i += 1
                continue
            if ch == quote:
                break
            chars.append(ch)
            i += 1

        if not chars:
            return None

        code_escaped = "".join(chars)
        try:
            code = json.loads(f'"{code_escaped}"')
        except Exception:
            # 非严格兜底：尽量保留可读内容，避免完全丢参
            code = (
                code_escaped
                .replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace('\\"', '"')
                .replace("\\\\", "\\")
            )

        code = str(code).strip()
        if not code:
            return None
        return {"code": code}
    
    async def _execute_single_call(
        self,
        tool_call: ToolCall,
        context: Dict[str, Any],
        skip_validation: bool = False
    ) -> ToolCallResult:
        """
        执行单个工具调用
        
        Args:
            tool_call: 工具调用请求
            context: 上下文信息
            skip_validation: 是否跳过 Schema 参数校验（默认 False）
                True  → execute_direct_tool_call() 调用时使用，
                        参数来自规划引擎，工具 execute() 内部自行做别名容错，
                        无需网关再做严格校验（否则 file_path vs path 等别名会误判 validation_error）
                False → execute_tool_calls() 调用时使用（LLM 原生 tool_calls 路径），
                        LLM 可能传入类型错误或缺失字段，需要严格校验拦截
            
        Returns:
            工具调用结果
        """
        start_time = datetime.now()
        
        logger.info(
            f"{Fore.BLUE}执行工具调用: {tool_call.tool_name} "
            f"(call_id={tool_call.call_id}, "
            f"skip_validation={skip_validation}){Style.RESET_ALL}"
        )
        
        # 步骤 1: 查找工具
        tool = self.get_tool(tool_call.tool_name)
        
        if tool is None:
            logger.warning(
                f"{Fore.YELLOW}工具不存在: {tool_call.tool_name}{Style.RESET_ALL}"
            )
            
            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
            
            return ToolCallResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                status=ToolCallStatus.NOT_FOUND,
                error=f"Tool not found: {tool_call.tool_name}",
                execution_time_ms=elapsed_ms
            )
        
        # 步骤 2: 参数验证（仅 LLM 原生工具调用路径才执行严格校验）
        # 背景：规划引擎生成的参数名（如 file_path）与工具 Schema 中的字段名（如 path）
        # 可能存在别名差异，工具的 execute() 方法内部已做别名容错处理，
        # 因此 execute_direct_tool_call() 调用时需跳过此校验，避免误判 validation_error。
        schema = self._tool_schemas.get(tool_call.tool_name)
        validated_args = tool_call.arguments
        
        if schema and not skip_validation:
            validated_args = self._validate_arguments(
                tool_call.tool_name,
                tool_call.arguments,
                schema
            )
            
            if validated_args is None:
                elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
                
                return ToolCallResult(
                    call_id=tool_call.call_id,
                    tool_name=tool_call.tool_name,
                    status=ToolCallStatus.VALIDATION_ERROR,
                    error="Argument validation failed",
                    execution_time_ms=elapsed_ms
                )
        elif skip_validation:
            logger.debug(
                f"{Fore.CYAN}[ToolCallingGateway] 跳过 Schema 校验（直接调用模式），"
                f"由工具 execute() 自行处理参数别名容错{Style.RESET_ALL}"
            )
        
        # 步骤 3: 执行工具
        try:
            # 检查工具是否有 execute 方法
            if not hasattr(tool, "execute"):
                raise AttributeError(f"Tool {tool_call.tool_name} has no 'execute' method")
            
            # ── 注入运行时上下文 ────────────────────────────────
            # 如果工具支持 update_context 方法，注入 context（包含 stream_callback、pending_user_inputs 等）
            # 注意：只有当 context 中有值时才传递，避免覆盖工具已有值
            if hasattr(tool, "update_context") and callable(tool.update_context):
                stream_callback = context.get("stream_callback")
                pending_confirmations = context.get("pending_confirmations")
                pending_user_inputs = context.get("pending_user_inputs")
                
                # 只有当 context 中存在该值时才传递，避免覆盖工具已保存的引用
                tool.update_context(
                    stream_callback=stream_callback if stream_callback is not None else None,
                    pending_confirmations=pending_confirmations if pending_confirmations is not None else None,
                    pending_user_inputs=pending_user_inputs if pending_user_inputs is not None else None
                )
            
            # 调用工具的 execute 方法
            execute_func = getattr(tool, "execute")
            
            # 如果是异步函数，使用 await
            if asyncio.iscoroutinefunction(execute_func):
                result = await asyncio.wait_for(
                    execute_func(validated_args),
                    timeout=self._default_timeout
                )
            else:
                result = await asyncio.to_thread(
                    execute_func,
                    validated_args
                )
            
            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
            
            logger.info(
                f"{Fore.GREEN}工具调用成功: {tool_call.tool_name}, "
                f"耗时: {elapsed_ms:.2f}ms{Style.RESET_ALL}"
            )
            
            return ToolCallResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                status=ToolCallStatus.SUCCESS,
                result=result,
                execution_time_ms=elapsed_ms
            )
            
        except asyncio.TimeoutError:
            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
            
            logger.error(
                f"{Fore.RED}工具调用超时: {tool_call.tool_name} "
                f"(>{self._default_timeout}s){Style.RESET_ALL}"
            )
            
            return ToolCallResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                status=ToolCallStatus.TIMEOUT,
                error=f"Tool execution timed out (> {self._default_timeout}s)",
                execution_time_ms=elapsed_ms
            )
            
        except ValidationError as e:
            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
            
            logger.error(
                f"{Fore.RED}参数验证失败: {tool_call.tool_name}, {e}{Style.RESET_ALL}"
            )
            
            return ToolCallResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                status=ToolCallStatus.VALIDATION_ERROR,
                error=f"Validation error: {str(e)}",
                execution_time_ms=elapsed_ms
            )
            
        except Exception as e:
            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
            
            logger.error(
                f"{Fore.RED}工具调用失败: {tool_call.tool_name}, {e}{Style.RESET_ALL}"
            )
            
            return ToolCallResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                status=ToolCallStatus.FAILURE,
                error=str(e),
                execution_time_ms=elapsed_ms
            )
    
    def _validate_arguments(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        schema: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        验证工具参数
        
        Args:
            tool_name: 工具名称
            arguments: 输入参数
            schema: 参数模式
            
        Returns:
            验证后的参数，如果验证失败返回 None
        """
        # 简化的参数验证
        # 实际应用中可以使用 jsonschema 库进行完整验证
        
        required_fields = schema.get("required", [])
        properties = schema.get("properties", {})
        
        # 检查必需字段
        for field in required_fields:
            if field not in arguments:
                logger.warning(
                    f"{Fore.YELLOW}缺少必需参数: {tool_name}.{field}{Style.RESET_ALL}"
                )
                return None
        
        # 简单的类型检查
        for key, value in arguments.items():
            if key in properties:
                expected_type = properties[key].get("type")
                if expected_type and not self._check_type(value, expected_type):
                    logger.warning(
                        f"{Fore.YELLOW}参数类型错误: {tool_name}.{key}, "
                        f"expected {expected_type}, got {type(value).__name__}{Style.RESET_ALL}"
                    )
                    return None
        
        return arguments
    
    def _check_type(self, value: Any, expected_type: str) -> bool:
        """
        检查值类型是否匹配
        
        Args:
            value: 要检查的值
            expected_type: 期望的类型
            
        Returns:
            是否匹配
        """
        type_mapping = {
            "string": (str,),
            "integer": (int,),
            "number": (int, float),
            "boolean": (bool,),
            "array": (list, tuple),
            "object": (dict,)
        }
        
        expected_types = type_mapping.get(expected_type, (object,))
        return isinstance(value, expected_types)
    
    async def execute_direct_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        call_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> "ToolCallResult":
        """
        直接执行工具调用（ExecutionEngine 专用入口）
        
        与 execute_tool_calls() 不同，该方法不需要 LLM 的 tool_calls 格式响应，
        而是直接接受工具名称和参数，适用于规划执行模式（Planning → Execution）下的
        工具调用。这样 ExecutionEngine 就可以把所有工具执行流量都路由到网关，
        统一享受网关的参数校验、日志记录、超时控制、统计监控等能力。
        
        使用场景：
        - ExecutionEngine 在执行 plan.steps 中的 action=tool 步骤时调用
        - 由规划引擎生成执行计划，再由执行引擎通过此方法路由到网关
        
        与 execute_tool_calls() 的区别：
        - execute_tool_calls(): 解析 LLM 的 tool_calls 响应 → 批量执行
        - execute_direct_tool_call(): 直接指定工具名和参数 → 单次执行
        
        Args:
            tool_name: 要执行的工具名称（必须已在网关中注册）
            arguments: 工具参数字典（JSON-serializable）
            call_id: 调用 ID（可选，不传则自动生成）
            context: 执行上下文（可选，包含 stream_callback、pending_user_inputs 等）
            
        Returns:
            ToolCallResult: 工具执行结果（含状态、结果数据、耗时等）
        """
        import uuid as _uuid
        
        # 自动生成调用 ID（用于日志追踪）
        effective_call_id = call_id or f"direct-{_uuid.uuid4().hex[:12]}"
        
        logger.info(
            f"{Fore.BLUE}[ToolCallingGateway] 直接工具调用: "
            f"tool={tool_name}, call_id={effective_call_id}{Style.RESET_ALL}"
        )
        logger.debug(
            f"{Fore.CYAN}[ToolCallingGateway] 工具参数: {arguments}{Style.RESET_ALL}"
        )
        
        # 构造 ToolCall 对象（与 LLM 原生 tool_calls 路径使用相同的结构）
        tool_call = ToolCall(
            call_id=effective_call_id,
            tool_name=tool_name,
            arguments=arguments,
            raw_data={
                # 标记来源，方便调试区分原生 tool_calls 和直接调用
                "source": "direct_call",
                "tool_name": tool_name,
                "arguments": arguments
            }
        )
        
        # 复用内部的单次执行逻辑（超时控制、错误处理等）
        # 注意：skip_validation=True 跳过严格 Schema 校验
        # 原因：规划引擎生成的参数名（如 file_path）可能与 Schema 定义（如 path）存在别名差异，
        #       工具的 execute() 内部已做容错（params.get("path") or params.get("file_path") ...），
        #       由工具自身处理参数兼容，避免网关误判 validation_error 导致工具无法执行
        # context 用于传递 stream_callback、pending_user_inputs 等运行时信息
        actual_context = context if context is not None else {}
        result = await self._execute_single_call(tool_call, actual_context, skip_validation=True)
        
        # 更新统计信息
        self._stats["total_calls"] += 1
        if result.status == ToolCallStatus.SUCCESS:
            self._stats["successful_calls"] += 1
            logger.info(
                f"{Fore.GREEN}[ToolCallingGateway] 直接工具调用成功: "
                f"tool={tool_name}, 耗时={result.execution_time_ms:.2f}ms{Style.RESET_ALL}"
            )
        else:
            self._stats["failed_calls"] += 1
            logger.warning(
                f"{Fore.YELLOW}[ToolCallingGateway] 直接工具调用失败: "
                f"tool={tool_name}, status={result.status.value}, "
                f"error={result.error}{Style.RESET_ALL}"
            )
        
        # 追加到调用历史
        self._call_history.append(result)
        if len(self._call_history) > 100:
            self._call_history = self._call_history[-100:]
        
        return result
    
    def format_results_for_llm(self, results: List[ToolCallResult]) -> List[Dict[str, Any]]:
        """
        格式化工具调用结果，返回给 LLM 的格式
        
        Args:
            results: 工具调用结果列表
            
        Returns:
            格式化后的结果列表
        """
        formatted = []
        
        for result in results:
            if result.status == ToolCallStatus.SUCCESS:
                formatted.append({
                    "role": "tool",
                    "tool_call_id": result.call_id,
                    "name": result.tool_name,
                    # 与 to_dict 保持一致：统一允许非 JSON 原生类型通过 str 兜底序列化。
                    "content": json.dumps(result.result, ensure_ascii=False, indent=2, default=str)
                })
            else:
                formatted.append({
                    "role": "tool",
                    "tool_call_id": result.call_id,
                    "name": result.tool_name,
                    "content": f"Error: {result.error}"
                })
        
        return formatted
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            统计信息字典
        """
        total = self._stats["total_calls"]
        return {
            **self._stats,
            "success_rate": self._stats["successful_calls"] / max(1, total),
            "available_tools": list(self._tools.keys())
        }
    
    def reset_stats(self) -> None:
        """
        重置统计信息
        """
        self._stats = {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0
        }
        self._call_history.clear()
        logger.info(f"{Fore.CYAN}工具调用网关统计信息已重置{Style.RESET_ALL}")


# =============================================================================
# 便捷函数
# =============================================================================

def create_tool_calling_gateway() -> ToolCallingGateway:
    """
    创建工具调用网关实例的便捷函数
    
    Returns:
        新的 ToolCallingGateway 实例
    """
    return ToolCallingGateway()


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    import sys
    
    # 配置日志
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
               "<level>{message}</level>"
    )
    
    # 测试 ToolCallingGateway
    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Tool Calling Gateway 测试{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
    
    gateway = create_tool_calling_gateway()
    print(f"创建工具调用网关: {gateway}")
    
    # 测试解析 OpenAI 格式
    openai_response = {
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
    
    tool_calls = gateway._parse_tool_calls(openai_response)
    print(f"解析 OpenAI 格式: {tool_calls}")
    
    # 测试解析 Anthropic 格式
    anthropic_response = {
        "content": [
            {
                "type": "tool_use",
                "id": "call-2",
                "name": "calculate",
                "input": {"expression": "2 + 2"}
            }
        ]
    }
    
    tool_calls = gateway._parse_tool_calls(anthropic_response)
    print(f"解析 Anthropic 格式: {tool_calls}")
    
    # 测试统计
    stats = gateway.get_stats()
    print(f"统计信息: {stats}")
    
    print(f"\n{Fore.GREEN}测试完成!{Style.RESET_ALL}\n")
