"""
统一推理引擎 (Inference Engine)
================================

本模块是 LLM Hub 的核心，负责统一管理所有 LLM 推理请求。

功能特点：
1. 统一推理接口，屏蔽底层供应商差异
2. 集成 Prompt 构建器、模型选择、流式输出
3. 支持请求预处理和结果后处理
4. 集成监控和日志记录

作者: AI Agent Team
创建时间: 2026-02-12
"""

import asyncio
from typing import Dict, List, Any, Optional, AsyncIterator, Tuple
from loguru import logger
from colorama import Fore, Style, Back
from datetime import datetime

# 导入 LLM Hub 内部模块
from app.core.config import get_default_model, infer_provider_from_model
from app.llm_hub.providers.base import LLMProvider, ModelMetadata
from app.llm_hub.prompt_builder import PromptBuilder
from app.llm_hub.streaming import StreamingManager, StreamChunk


class InferenceConfig:
    """
    推理配置
    
    控制推理过程中的各项参数
    """
    
    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        system_prompt: Optional[str] = None,
        context: Optional[List[Dict[str, Any]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        provider: Optional[str] = None  # 强制指定供应商
    ):
        """
        初始化推理配置
        
        Args:
            model: 模型 ID
            temperature: 温度参数 (0.0 - 2.0)
            max_tokens: 最大输出 tokens
            stream: 是否使用流式输出
            system_prompt: 系统提示词
            context: 上下文信息
            tools: 可用工具定义
            provider: 强制指定供应商 (可选)
        """
        resolved_provider = (provider or "").strip().lower()
        self.model = model or get_default_model(
            "anthropic" if resolved_provider == "anthropic" else "openai"
        )
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.stream = stream
        self.system_prompt = system_prompt
        self.context = context or []
        self.tools = tools or []
        self.provider = provider
        
        logger.info(
            f"{Fore.BLUE}创建推理配置: model={self.model}, stream={stream}, "
            f"temperature={temperature}{Style.RESET_ALL}"
        )


class InferenceResult:
    """
    推理结果
    
    统一不同供应商的响应格式
    """
    
    def __init__(
        self,
        content: str,
        raw_response: Dict[str, Any],
        model: str,
        provider: str,
        usage: Optional[Dict[str, Any]] = None,
        finish_reason: Optional[str] = None
    ):
        """
        初始化推理结果
        
        Args:
            content: 生成的文本内容
            raw_response: 原始响应数据
            model: 使用的模型
            provider: 供应商名称
            usage: Token 使用统计
            finish_reason: 结束原因 (stop, length, tool_calls, etc.)
        """
        self.content = content
        self.raw_response = raw_response
        self.model = model
        self.provider = provider
        self.usage = usage or {}
        self.finish_reason = finish_reason
        self.created_at = datetime.now()
    
    def __repr__(self) -> str:
        """返回结果的字符串表示"""
        return (
            f"InferenceResult(model={self.model}, provider={self.provider}, "
            f"content_len={len(self.content)}, finish_reason={self.finish_reason})"
        )


class InferenceEngine:
    """
    统一推理引擎
    
    这是 LLM Hub 的核心组件，提供统一的推理接口。
    
    工作流程：
    1. 接收推理请求和配置
    2. 构建 Prompt（使用 PromptBuilder）
    3. 选择模型（从注册中心获取）
    4. 执行推理（调用供应商适配器）
    5. 后处理结果
    6. 返回统一的响应格式
    """
    
    def __init__(
        self,
        provider: LLMProvider,
        model_registry: Any,  # ModelRegistry
        prompt_builder: Optional[PromptBuilder] = None,
        streaming_manager: Optional[StreamingManager] = None,
        tool_gateway: Optional[Any] = None,  # ToolCallingGateway 实例（可选）
        max_tool_iterations: int = 20  # 工具调用循环的最大迭代次数，防止无限循环
    ):
        """
        初始化推理引擎
        
        Args:
            provider: 默认 LLM 供应商实例
            model_registry: 模型注册中心
            prompt_builder: Prompt 构建器（可选，将自动创建）
            streaming_manager: 流式输出管理器（可选，将自动创建）
            tool_gateway: 工具调用网关实例（可选）。
                         当 LLM 响应包含 tool_calls（finish_reason=tool_calls）时，
                         自动通过网关执行工具并将结果追加到对话，再次调用 LLM，
                         形成"原生工具调用循环"，直到 LLM 不再请求工具或达到最大迭代次数。
            max_tool_iterations: 工具调用循环的最大迭代次数（默认 5 次），
                                 避免无限递归调用工具。
        """
        self._provider = provider
        self._model_registry = model_registry
        
        # 初始化 Prompt 构建器
        self._prompt_builder = prompt_builder or PromptBuilder()
        logger.info(f"{Fore.CYAN}初始化 PromptBuilder: {type(self._prompt_builder).__name__}{Style.RESET_ALL}")
        
        # 初始化流式输出管理器
        self._streaming_manager = streaming_manager or StreamingManager()
        logger.info(f"{Fore.CYAN}初始化 StreamingManager: {type(self._streaming_manager).__name__}{Style.RESET_ALL}")
        
        # ─── 工具调用网关（核心新增功能）───────────────────────────────
        # 当 config.tools 非空时，LLM 可能返回 finish_reason=tool_calls，
        # 此时 InferenceEngine 会自动调用 tool_gateway 执行工具，
        # 将结果追加到对话历史，再次调用 LLM，形成原生工具调用循环。
        # 如果不传入 tool_gateway，则不进行原生工具调用循环（保持原有行为）。
        logger.info(f"{Fore.CYAN}初始化 ToolCallingGateway: {type(tool_gateway).__name__}{Style.RESET_ALL}")
        logger.info(f"{Fore.CYAN}最大工具调用迭代次数: {max_tool_iterations}{Style.RESET_ALL}")
        logger.info(f"{Fore.CYAN}工具调用网关: {tool_gateway}{Style.RESET_ALL}")
        self._tool_gateway = tool_gateway
        self._max_tool_iterations = max_tool_iterations
        
        if tool_gateway is not None:
            logger.info(
                f"{Fore.GREEN}工具调用网关已接入 InferenceEngine，"
                f"最大工具调用迭代次数: {max_tool_iterations}{Style.RESET_ALL}"
            )
        else:
            logger.info(
                f"{Fore.YELLOW}工具调用网关未配置，LLM 原生工具调用循环不可用{Style.RESET_ALL}"
            )
        
        # 请求计数器
        self._request_count = 0
        self._error_count = 0
        
        # 请求历史（用于统计）
        self._request_history: List[Dict[str, Any]] = []
        
        logger.info(
            f"{Fore.GREEN}推理引擎初始化完成，默认供应商: {type(provider).__name__}{Style.RESET_ALL}"
        )
    
    def set_provider(self, provider: LLMProvider) -> None:
        """
        设置默认供应商
        
        Args:
            provider: 新的默认供应商实例
        """
        old_provider_name = type(self._provider).__name__
        self._provider = provider
        new_provider_name = type(provider).__name__
        
        logger.info(
            f"{Fore.CYAN}切换默认供应商: {old_provider_name} -> {new_provider_name}{Style.RESET_ALL}"
        )
    
    async def infer(
        self,
        messages: List[Dict[str, str]],
        config: Optional[InferenceConfig] = None
    ) -> InferenceResult:
        """
        执行非流式推理
        
        Args:
            messages: 对话消息列表
            config: 推理配置
            
        Returns:
            InferenceResult: 推理结果
        """
        config = config or InferenceConfig()
        self._request_count += 1
        request_id = f"req-{self._request_count:06d}"
        
        logger.info(
            f"{Fore.BLUE}[{request_id}] 开始推理请求: model={config.model}, "
            f"stream={config.stream}, messages_count={len(messages)}{Style.RESET_ALL}"
        )
        
        try:
            # 步骤 1: 构建 Prompt
            logger.info(f"{Fore.BLUE}[{request_id}] 步骤 1/4: 构建 Prompt{Style.RESET_ALL}")
            prompt_messages = self._prompt_builder.build(
                messages=messages,
                system_prompt=config.system_prompt,
                context=config.context,
                tools=config.tools
            )
            
            # logger.info(f"{Fore.CYAN}[{request_id}] 构建 Prompt: {prompt_messages}{Style.RESET_ALL}")
            # 步骤 2: 选择模型和供应商
            logger.info(f"{Fore.BLUE}[{request_id}] 步骤 2/4: 选择模型{Style.RESET_ALL}")
            model_info, provider = self._select_model(config)
            
            # 准备供应商配置
            provider_config = {
                "model": config.model,
                "temperature": config.temperature,
                "max_tokens": config.max_tokens,
                # 传递工具定义（用于 function calling）
                "tools": config.tools if config.tools else None
            }
            
            # 过滤掉 None 值
            provider_config = {k: v for k, v in provider_config.items() if v is not None}
            
            # 步骤 3: 执行推理
            logger.info(f"{Fore.BLUE}[{request_id}] 步骤 3/4: 执行推理 (供应商: {type(provider).__name__}){Style.RESET_ALL}")
            start_time = datetime.now()
            
            raw_response = await provider.chat(prompt_messages, provider_config)

            # todo 一会解开注释
            # logger.info(f"{Fore.CYAN}[{request_id}] 原始响应: {raw_response}{Style.RESET_ALL}")
            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(
                f"{Fore.GREEN}[{request_id}] 首次推理完成，耗时: {elapsed_ms:.2f}ms{Style.RESET_ALL}"
            )
            
            # 步骤 3.5: 工具调用循环（仅当工具网关已配置且本次请求携带工具定义时才激活）
            # ─────────────────────────────────────────────────────────────────
            # 原生工具调用流程：
            #   1. LLM 返回 finish_reason=tool_calls，说明 LLM 想要调用工具
            #   2. 通过 ToolCallingGateway 执行 LLM 请求的工具
            #   3. 将 assistant 消息（含 tool_calls）和工具执行结果追加到对话历史
            #   4. 再次调用 LLM，让其基于工具结果生成最终回复
            #   5. 重复上述步骤，直到 LLM 不再请求工具或达到最大迭代次数
            # ─────────────────────────────────────────────────────────────────

            # todo 一会解开注释
            # logger.info(f"{Fore.CYAN}[{request_id}] 工具调用网关: {self._tool_gateway}{Style.RESET_ALL}")
            # todo 一会解开注释
            # logger.info(f"{Fore.CYAN}[{request_id}] 工具定义传入: {config.tools}{Style.RESET_ALL}")
            if self._tool_gateway is not None and config.tools:
                logger.info(
                    f"{Fore.BLUE}[{request_id}] 步骤 3.5: 检测工具调用循环条件："
                    f"tool_gateway={type(self._tool_gateway).__name__}, "
                    f"tools_count={len(config.tools)}{Style.RESET_ALL}"
                )
                raw_response, prompt_messages = await self._handle_tool_calling_loop(
                    initial_response=raw_response,
                    messages=prompt_messages,
                    provider=provider,
                    provider_config=provider_config,
                    request_id=request_id
                )
            else:
                if self._tool_gateway is None:
                    logger.debug(
                        f"{Fore.CYAN}[{request_id}] 工具调用网关未配置，跳过工具调用循环{Style.RESET_ALL}"
                    )
                elif not config.tools:
                    logger.debug(
                        f"{Fore.CYAN}[{request_id}] 当前请求未携带工具定义，跳过工具调用循环{Style.RESET_ALL}"
                    )
            
            # 步骤 4: 后处理结果
            logger.info(f"{Fore.BLUE}[{request_id}] 步骤 4/4: 后处理结果{Style.RESET_ALL}")
            result = self._postprocess_result(raw_response, config, model_info)
            
            # 记录请求历史
            self._record_request(request_id, config, result, elapsed_ms)
            
            logger.info(
                f"{Fore.GREEN}[{request_id}] 推理请求成功完成，结果长度: {len(result.content)} 字符{Style.RESET_ALL}"
            )
            # 打印推理结果
            # todo 一会解开注释
            # logger.info(f"{Fore.GREEN}[{request_id}] 推理结果: {result.content}{Style.RESET_ALL}")
            
            return result
            
        except Exception as e:
            self._error_count += 1
            logger.error(
                f"{Fore.RED}[{request_id}] 推理请求失败: {e}{Style.RESET_ALL}"
            )
            raise
    
    async def infer_stream(
        self,
        messages: List[Dict[str, str]],
        config: Optional[InferenceConfig] = None
    ) -> AsyncIterator[StreamChunk]:
        """
        执行流式推理
        
        Args:
            messages: 对话消息列表
            config: 推理配置
            
        Yields:
            StreamChunk: 流式输出块
        """
        config = config or InferenceConfig()
        config.stream = True  # 确保启用流式
        
        self._request_count += 1
        request_id = f"req-{self._request_count:06d}"
        
        logger.info(
            f"{Fore.BLUE}[{request_id}] 开始流式推理请求: model={config.model}, "
            f"messages_count={len(messages)}{Style.RESET_ALL}"
        )
        
        try:
            # 步骤 1: 构建 Prompt
            prompt_messages = self._prompt_builder.build(
                messages=messages,
                system_prompt=config.system_prompt,
                context=config.context,
                tools=config.tools
            )
            
            # 步骤 2: 选择模型和供应商
            model_info, provider = self._select_model(config)
            
            # 准备供应商配置
            provider_config = {
                "model": config.model,
                "temperature": config.temperature,
                "max_tokens": config.max_tokens,
                "tools": config.tools if config.tools else None
            }
            provider_config = {k: v for k, v in provider_config.items() if v is not None}
            
            # 步骤 3: 获取流式响应
            provider_name = type(provider).__name__.replace("Provider", "").lower()
            raw_stream = provider.stream(prompt_messages, provider_config)
            
            # 步骤 4: 标准化流式输出
            async for chunk in self._streaming_manager.stream_response(
                provider_name=provider_name,
                stream=raw_stream,
                config=config.__dict__
            ):
                yield chunk
            
            logger.info(
                f"{Fore.GREEN}[{request_id}] 流式推理请求完成{Style.RESET_ALL}"
            )
            
        except Exception as e:
            self._error_count += 1
            logger.error(
                f"{Fore.RED}[{request_id}] 流式推理请求失败: {e}{Style.RESET_ALL}"
            )
            raise
    
    async def _handle_tool_calling_loop(
        self,
        initial_response: Dict[str, Any],
        messages: List[Dict[str, Any]],
        provider: LLMProvider,
        provider_config: Dict[str, Any],
        request_id: str
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        工具调用循环处理器（Tool Calling Loop）
        
        当 LLM 响应包含 finish_reason=tool_calls 时，自动执行以下循环：
          1. 将 LLM 的 assistant 消息（含 tool_calls）追加到对话历史
          2. 通过 ToolCallingGateway 执行 LLM 请求的工具
          3. 将所有工具执行结果（role=tool 消息）追加到对话历史
          4. 再次调用 LLM，基于工具结果生成最终回复
          5. 重复上述过程，直到：
             - LLM 不再返回 tool_calls（任务完成）
             - 或达到 max_tool_iterations 上限（防止无限循环）
        
        Args:
            initial_response: 首次 LLM 调用的原始响应
            messages: 当前对话消息列表（会在循环中被追加）
            provider: LLM 供应商实例
            provider_config: 供应商配置参数
            request_id: 请求 ID（用于日志追踪）
            
        Returns:
            Tuple[最终 LLM 响应, 更新后的消息列表]
        """
        current_response = initial_response
        # 使用列表副本，避免修改原始消息列表
        current_messages = list(messages)
        
        logger.info(
            f"{Fore.CYAN}[{request_id}] 🔄 开始工具调用循环，"
            f"最大迭代次数: {self._max_tool_iterations}{Style.RESET_ALL}"
        )
        
        for iteration in range(self._max_tool_iterations):
            # ── 检查 LLM 是否请求工具调用 ──────────────────────────────────
            finish_reason = self._extract_finish_reason(current_response)
            
            if finish_reason != "tool_calls":
                # LLM 不再请求工具，循环正常结束
                logger.info(
                    f"{Fore.GREEN}[{request_id}] 工具调用循环正常结束 "
                    f"(第 {iteration} 次迭代，finish_reason={finish_reason}){Style.RESET_ALL}"
                )
                break
            
            logger.info(
                f"{Fore.BLUE}[{request_id}] 🔧 工具调用循环 - 第 {iteration + 1}/{self._max_tool_iterations} 次迭代{Style.RESET_ALL}"
            )
            
            # ── 步骤 A: 提取 assistant 消息（含 tool_calls）并追加到对话 ──
            # 必须将 assistant 的 tool_calls 消息加入对话，
            # 否则 LLM 会不知道之前请求了哪些工具
            assistant_msg = self._extract_assistant_message(current_response)
            if assistant_msg:
                current_messages.append(assistant_msg)
                logger.debug(
                    f"{Fore.CYAN}[{request_id}] 已追加 assistant 消息（含 tool_calls）到对话历史{Style.RESET_ALL}"
                )
            else:
                logger.warning(
                    f"{Fore.YELLOW}[{request_id}] 无法从响应中提取 assistant 消息，跳过本次追加{Style.RESET_ALL}"
                )
            
            # ── 步骤 B: 通过 ToolCallingGateway 执行 LLM 请求的工具 ──────
            logger.info(
                f"{Fore.BLUE}[{request_id}] 📦 正在通过 ToolCallingGateway 执行工具调用...{Style.RESET_ALL}"
            )
            
            try:
                tool_results = await self._tool_gateway.execute_tool_calls(current_response)
            except Exception as e:
                logger.error(
                    f"{Fore.RED}[{request_id}] ToolCallingGateway 执行工具失败: {e}，退出工具调用循环{Style.RESET_ALL}"
                )
                break
            
            if not tool_results:
                # 没有可执行的工具调用结果，异常情况，退出循环避免死锁
                logger.warning(
                    f"{Fore.YELLOW}[{request_id}] 工具调用结果为空（LLM 请求了工具但网关未执行任何工具），退出循环{Style.RESET_ALL}"
                )
                break
            
            logger.info(
                f"{Fore.GREEN}[{request_id}] ✅ 工具调用执行完成，共 {len(tool_results)} 个结果{Style.RESET_ALL}"
            )
            
            # ── 步骤 C: 将工具执行结果追加到对话历史 ───────────────────────
            # 每个工具结果对应一条 role=tool 的消息，包含 tool_call_id 和执行内容
            for tool_result in tool_results:
                result_msg = tool_result.to_dict()
                current_messages.append(result_msg)
                logger.debug(
                    f"{Fore.CYAN}[{request_id}] 已追加工具结果到对话历史: "
                    f"tool={tool_result.tool_name}, status={tool_result.status.value}{Style.RESET_ALL}"
                )
            
            # ── 步骤 D: 携带工具结果再次调用 LLM ─────────────────────────
            # ====== 【关键修复】在再次调用 LLM 前，截断过长的对话历史 ======
            current_messages = self._truncate_messages(current_messages, max_tokens=60000)
            
            logger.info(
                f"{Fore.BLUE}[{request_id}] 🤖 携带工具结果再次调用 LLM（对话历史共 {len(current_messages)} 条消息）{Style.RESET_ALL}"
            )
            
            try:
                loop_start = datetime.now()
                current_response = await provider.chat(current_messages, provider_config)
                loop_elapsed_ms = (datetime.now() - loop_start).total_seconds() * 1000
                
                logger.info(
                    f"{Fore.GREEN}[{request_id}] LLM 再次调用完成，耗时: {loop_elapsed_ms:.2f}ms{Style.RESET_ALL}"
                )
            except Exception as e:
                logger.error(
                    f"{Fore.RED}[{request_id}] 工具调用循环中 LLM 调用失败: {e}，退出循环{Style.RESET_ALL}"
                )
                break
        
        else:
            # for-else 语句：当循环正常跑完（未 break）时执行
            # 说明达到了最大迭代次数上限
            logger.warning(
                f"{Fore.YELLOW}[{request_id}] ⚠️ 工具调用循环达到最大迭代次数上限 "
                f"({self._max_tool_iterations} 次)，强制退出。"
                f"这可能意味着 LLM 持续请求工具调用，请检查工具实现或调整迭代次数。{Style.RESET_ALL}"
            )
        
        logger.info(
            f"{Fore.GREEN}[{request_id}] 工具调用循环结束，"
            f"对话历史共 {len(current_messages)} 条消息{Style.RESET_ALL}"
        )
        
        return current_response, current_messages
    
    def _extract_assistant_message(self, raw_response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        从 LLM 原始响应中提取 assistant 消息体（包含 tool_calls）
        
        当 LLM 返回 finish_reason=tool_calls 时，响应体的 choices[0].message 包含：
        - role: "assistant"
        - content: null 或 空字符串
        - tool_calls: [{id, type, function: {name, arguments}}]
        
        必须将这个消息追加到对话历史中，才能让 LLM 知道它之前请求了哪些工具。
        
        Args:
            raw_response: LLM 的原始响应字典
            
        Returns:
            assistant 消息字典，如果无法提取则返回 None
        """
        try:
            # OpenAI 格式: {"choices": [{"message": {...}}]}
            if "choices" in raw_response and raw_response["choices"]:
                choice = raw_response["choices"][0]
                message = choice.get("message")
                
                if message and isinstance(message, dict):
                    # 确保消息有正确的 role 字段
                    if "role" not in message:
                        message = {"role": "assistant", **message}
                    
                    logger.debug(
                        f"{Fore.CYAN}提取 assistant 消息成功，"
                        f"tool_calls 数量: {len(message.get('tool_calls', []))}{Style.RESET_ALL}"
                    )
                    return message
            
            # Anthropic 格式暂不支持提取 assistant 消息（其工具调用格式不同）
            # Anthropic 使用 content blocks 而不是 tool_calls 字段
            logger.debug(
                f"{Fore.YELLOW}响应格式不是 OpenAI 标准格式，无法提取 assistant 消息{Style.RESET_ALL}"
            )
            return None
            
        except Exception as e:
            logger.warning(
                f"{Fore.YELLOW}提取 assistant 消息时发生异常: {e}{Style.RESET_ALL}"
            )
            return None
    
    def _select_model(
        self,
        config: InferenceConfig
    ) -> tuple[ModelMetadata, LLMProvider]:
        """
        选择模型和供应商
        
        Args:
            config: 推理配置
            
        Returns:
            (模型元数据, 供应商实例)
        """
        # 如果配置了强制供应商，使用该供应商
        if config.provider:
            provider_name = config.provider.lower()
            if provider_name == "openai":
                from app.llm_hub.providers.openai import OpenAIProvider
                provider = OpenAIProvider()
            elif provider_name == "anthropic":
                from app.llm_hub.providers.anthropic import AnthropicProvider
                provider = AnthropicProvider()
            else:
                logger.warning(f"{Fore.YELLOW}未知供应商: {provider_name}，使用默认供应商{Style.RESET_ALL}")
                provider = self._provider
        else:
            provider = self._provider

        resolved_provider_name = (
            config.provider.lower()
            if config.provider
            else type(provider).__name__.replace("Provider", "").lower()
        )
        logger.debug(
            f"{Fore.CYAN}模型选择开始 | config.model={config.model} | "
            f"provider={resolved_provider_name}{Style.RESET_ALL}"
        )
        # 获取模型元数据
        model_metadata = self._model_registry.get_model(config.model)
        logger.debug(f"{Fore.CYAN}模型注册信息: {model_metadata}{Style.RESET_ALL}")
        if model_metadata is None:
            logger.warning(
                f"{Fore.YELLOW}模型 {config.model} 未在注册中心找到，"
                f"将按供应商规则动态补齐元数据{Style.RESET_ALL}"
            )
            # 返回一个默认的模型元数据
            model_metadata = ModelMetadata(
                model_id=config.model,
                provider=(
                    config.provider.lower()
                    if config.provider
                    else infer_provider_from_model(config.model)
                ),
                model_name=config.model,
                capabilities=["chat", "tool_use", "vision"] if resolved_provider_name == "anthropic" else ["chat", "function_call"],
                context_window=200000 if resolved_provider_name == "anthropic" else 128000,
                max_output_tokens=4096
            )
        
        logger.info(
            f"{Fore.BLUE}选择模型: {model_metadata.model_id} (供应商: {model_metadata.provider}){Style.RESET_ALL}"
        )
        
        return model_metadata, provider
    
    def _postprocess_result(
        self,
        raw_response: Dict[str, Any],
        config: InferenceConfig,
        model_info: ModelMetadata
    ) -> InferenceResult:
        """
        后处理推理结果
        
        提取统一格式的结果字段
        
        Args:
            raw_response: 原始响应
            config: 推理配置
            model_info: 模型元数据
            
        Returns:
            标准化后的推理结果
        """
        # 从原始响应中提取内容
        content = self._extract_content(raw_response)
        
        # 提取结束原因
        finish_reason = self._extract_finish_reason(raw_response)
        
        # 提取使用统计
        usage = self._extract_usage(raw_response)
        
        result = InferenceResult(
            content=content,
            raw_response=raw_response,
            model=config.model,
            provider=model_info.provider,
            usage=usage,
            finish_reason=finish_reason
        )
        
        logger.info(
            f"{Fore.BLUE}后处理完成: content_len={len(content)}, "
            f"finish_reason={finish_reason}{Style.RESET_ALL}"
        )
        
        return result

    def _truncate_messages(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int = 60000
    ) -> List[Dict[str, Any]]:
        """
        截断对话历史，防止超过模型的上下文限制
        
        当对话历史过长时，保留：
        - 第一条系统消息（如果有的消息）
        - 最近的消息（优先保留 user 消息和 tool 结果）        
        重要：必须保持消息的完整性——tool 消息必须紧跟在对应的 assistant 消息后面
        
        Args:
            messages: 对话消息列表
            max_tokens: 最大 token 数量（近似值）
            
        Returns:
            截断后的消息列表
        """
        if not messages:
            return messages
        
        # 简单估算：假设平均每个字符等于 1/4 token
        max_chars = max_tokens * 4
        
        # 计算当前总字符数
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if content:
                total_chars += len(str(content))
        
        # 如果没有超过限制，直接返回
        if total_chars <= max_chars:
            return messages
        
        logger.warning(
            f"{Fore.YELLOW}对话历史过长（{total_chars} 字符），"
            f"进行截断（目标: {max_chars} 字符）{Style.RESET_ALL}"
        )
        
        # 保留策略：
        # 1. 保留第一条系统消息
        # 2. 从后往前保留消息块（每个 block 包含 assistant+tool 或单个 user）
        # 3. 确保 tool 消息不会被单独保留
        
        system_message = None
        remaining_messages = []
        
        for msg in messages:
            role = msg.get("role", "")
            if role == "system" and system_message is None:
                system_message = msg
            else:
                remaining_messages.append(msg)
        
        # 从后往前保留消息块
        # 规则：
        # - user 消息可以单独保留
        # - assistant 消息如果有 tool_calls，必须和它的 tool 响应一起保留
        # - tool 消息必须和前面的 assistant 消息一起保留
        truncated_remaining = []
        current_chars = 0
        
        i = len(remaining_messages) - 1
        while i >= 0:
            msg = remaining_messages[i]
            role = msg.get("role", "")
            content = str(msg.get("content", ""))
            msg_chars = len(content)
            
            # 如果当前消息是 tool，需要把前面的 assistant 也一起保留
            if role == "tool":
                # 找到对应的 assistant 消息
                block_chars = msg_chars
                block_msgs = [msg]
                
                j = i - 1
                while j >= 0:
                    prev_msg = remaining_messages[j]
                    prev_role = prev_msg.get("role", "")
                    if prev_role == "assistant" and prev_msg.get("tool_calls"):
                        # 找到带 tool_calls 的 assistant，添加到 block
                        block_chars += len(str(prev_msg.get("content", "")))
                        block_msgs.insert(0, prev_msg)
                        break
                    elif prev_role == "user":
                        # 遇到 user 消息，停止
                        break
                    else:
                        j -= 1
                
                # 检查是否可以添加这个 block
                if current_chars + block_chars <= max_chars * 0.8:
                    for bm in block_msgs:
                        truncated_remaining.insert(0, bm)
                    current_chars += block_chars
                    i = j  # 更新索引
                else:
                    break
            
            # 如果是 assistant 带 tool_calls
            elif role == "assistant" and msg.get("tool_calls"):
                # 这个 assistant 必须和后面的 tool 消息一起保留
                block_chars = msg_chars
                block_msgs = [msg]
                
                j = i + 1
                while j < len(remaining_messages):
                    next_msg = remaining_messages[j]
                    next_role = next_msg.get("role", "")
                    if next_role == "tool":
                        block_chars += len(str(next_msg.get("content", "")))
                        block_msgs.append(next_msg)
                        j += 1
                    else:
                        break
                
                if current_chars + block_chars <= max_chars * 0.8:
                    for bm in block_msgs:
                        truncated_remaining.insert(0, bm)
                    current_chars += block_chars
                    i = j - 1
                else:
                    break
            
            # 其他消息（user 或不带 tool_calls 的 assistant）
            else:
                if current_chars + msg_chars <= max_chars * 0.8:
                    truncated_remaining.insert(0, msg)
                    current_chars += msg_chars
                else:
                    break
            
            i -= 1
        
        # 组合最终结果
        result = []
        if system_message:
            result.append(system_message)
        result.extend(truncated_remaining)
        
        # 确保有内容且最后一条是 user/function/tool
        if not result or (result and result[-1].get("role") not in ("user", "function", "tool", "assistant")):
            # 如果没有内容，添加一个默认 user 消息
            if not result:
                result = [{"role": "user", "content": "继续"}]
            else:
                # 找到最后一条 user/function/tool 消息，确保它在最后
                valid_msg = None
                for msg in reversed(result):
                    if msg.get("role") in ("user", "function", "tool"):
                        valid_msg = msg
                        break
                if valid_msg and valid_msg != result[-1]:
                    result.remove(valid_msg)
                    result.append(valid_msg)
        
        # 组合最终结果
        result = []
        if system_message:
            result.append(system_message)
        result.extend(truncated_remaining)
        
        # 确保有内容
        if not result:
            # 如果所有消息都被删除了，至少保留一条 user 消息
            result = [{"role": "user", "content": "继续"}]
        
        # 重新计算字符数
        new_chars = sum(len(str(msg.get("content", ""))) for msg in result)
        logger.info(
            f"{Fore.GREEN}对话历史截断完成: {len(messages)} 条 -> {len(result)} 条，"
            f"{total_chars} 字符 -> {new_chars} 字符{Style.RESET_ALL}"
        )
        
        return result
    
    def _extract_content(self, raw_response: Dict[str, Any]) -> str:
        """
        从原始响应中提取文本内容
        
        Args:
            raw_response: 原始响应
            
        Returns:
            提取的文本内容
        """
        try:
            # NOTE: 首先检测 API 错误响应（如第三方代理返回的错误码）
            #       当 choices=None 且有错误状态码时，说明 API 调用失败
            #       必须抛出异常，而不是把错误信息当作 LLM 内容返回
            if raw_response.get("choices") is None:
                logger.info(f"{Fore.CYAN}提取内容失败: {raw_response.get("choices")}{Style.RESET_ALL}")
                status_code = raw_response.get("status")
                error_msg = raw_response.get("msg") or raw_response.get("error")
                if status_code is not None or error_msg is not None:
                    detail = f"status={status_code}, msg={error_msg}"
                    logger.error(
                        f"{Fore.RED}检测到 API 错误响应，拒绝将错误信息当作内容: {detail}{Style.RESET_ALL}"
                    )
                    raise ValueError(f"API 错误响应: {detail}")
            
            # OpenAI 格式
            if "choices" in raw_response and raw_response["choices"] is not None:
                logger.info(f"{Fore.CYAN}提取内容成功: {raw_response["choices"]}{Style.RESET_ALL}")
                choice = raw_response["choices"][0]
                if "message" in choice:
                    # 如果message是字符串，直接返回
                    if isinstance(choice["message"], str):
                        return choice["message"]    
                    return choice["message"].get("content", "")
                elif "delta" in choice:
                    # 如果delta是字符串，直接返回
                    if isinstance(choice["delta"], str):
                        return choice["delta"]      
                    return choice["delta"].get("content", "")
            
            # Anthropic 格式
            if "content" in raw_response:
                logger.info(f"{Fore.CYAN}提取内容成功: {raw_response["content"]}{Style.RESET_ALL}")
                # 如果content是字符串，直接返回
                if isinstance(raw_response["content"], str):
                    return raw_response["content"]      
                blocks = raw_response["content"]
                logger.info(f"{Fore.CYAN}提取内容成功: {blocks}{Style.RESET_ALL}")
                for block in blocks:
                    if block.get("type") == "text":
                        return block.get("text", "")
            
            # 其他格式，尝试通用提取
            return str(raw_response)
            
        except ValueError:
            # 明确的 API 错误，直接向上抛出，不需要 fallback
            raise
        except Exception as e:
            logger.warning(f"{Fore.YELLOW}提取内容失败: {e}，返回原始响应{Style.RESET_ALL}")
            return str(raw_response)
    
    def _extract_finish_reason(self, raw_response: Dict[str, Any]) -> Optional[str]:
        """
        从原始响应中提取结束原因
        
        Args:
            raw_response: 原始响应
            
        Returns:
            结束原因字符串
        """
        try:
            if "choices" in raw_response:
                return raw_response["choices"][0].get("finish_reason")
            if "stop_reason" in raw_response:
                return raw_response["stop_reason"]
            return None
        except Exception:
            return None
    
    def _extract_usage(self, raw_response: Dict[str, Any]) -> Dict[str, Any]:
        """
        从原始响应中提取使用统计
        
        Args:
            raw_response: 原始响应
            
        Returns:
            使用统计字典
        """
        try:
            if "usage" in raw_response:
                return raw_response["usage"]
            return {}
        except Exception:
            return {}
    
    def _record_request(
        self,
        request_id: str,
        config: InferenceConfig,
        result: InferenceResult,
        elapsed_ms: float
    ) -> None:
        """
        记录请求历史
        
        Args:
            request_id: 请求 ID
            config: 推理配置
            result: 推理结果
            elapsed_ms: 耗时（毫秒）
        """
        record = {
            "request_id": request_id,
            "model": config.model,
            "provider": result.provider,
            "content_length": len(result.content),
            "elapsed_ms": elapsed_ms,
            "timestamp": datetime.now().isoformat(),
            "success": True
        }
        
        self._request_history.append(record)
        
        # 只保留最近 1000 条记录
        if len(self._request_history) > 1000:
            self._request_history = self._request_history[-1000:]
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取推理引擎统计信息
        
        Returns:
            统计信息字典，包含请求数量、错误率、工具调用网关状态等
        """
        stats = {
            "total_requests": self._request_count,
            "successful_requests": self._request_count - self._error_count,
            "failed_requests": self._error_count,
            "error_rate": self._error_count / max(1, self._request_count),
            "provider": type(self._provider).__name__,
            # 工具调用网关状态
            "tool_gateway_enabled": self._tool_gateway is not None,
            "max_tool_iterations": self._max_tool_iterations
        }
        
        # 如果工具调用网关已配置，也返回网关的统计信息
        if self._tool_gateway is not None:
            try:
                gateway_stats = self._tool_gateway.get_stats()
                stats["tool_gateway_stats"] = gateway_stats
                logger.debug(
                    f"{Fore.CYAN}推理引擎统计信息中包含工具调用网关数据: "
                    f"total_tool_calls={gateway_stats.get('total_calls', 0)}{Style.RESET_ALL}"
                )
            except Exception as e:
                logger.warning(
                    f"{Fore.YELLOW}获取工具调用网关统计信息失败: {e}{Style.RESET_ALL}"
                )
        
        return stats
    
    def reset_stats(self) -> None:
        """
        重置统计信息
        """
        self._request_count = 0
        self._error_count = 0
        self._request_history.clear()
        logger.info(f"{Fore.CYAN}推理引擎统计信息已重置{Style.RESET_ALL}")


# =============================================================================
# 便捷函数
# =============================================================================

def create_inference_engine(
    provider: LLMProvider,
    model_registry: Any,
    tool_gateway: Optional[Any] = None,
    max_tool_iterations: int = 20
) -> InferenceEngine:
    """
    创建推理引擎实例的便捷函数
    
    Args:
        provider: LLM 供应商实例
        model_registry: 模型注册中心
        tool_gateway: 工具调用网关实例（可选）。
                     传入后，推理引擎将支持 LLM 原生工具调用循环。
                     当 LLM 响应包含 tool_calls 时，网关将自动执行工具并重新调用 LLM。
        max_tool_iterations: 工具调用循环最大迭代次数（默认 5 次）
        
    Returns:
        新的 InferenceEngine 实例
    """
    engine = InferenceEngine(
        provider=provider,
        model_registry=model_registry,
        tool_gateway=tool_gateway,
        max_tool_iterations=max_tool_iterations
    )
    
    if tool_gateway is not None:
        logger.info(
            f"{Fore.GREEN}已创建集成工具调用网关的推理引擎，"
            f"最大工具调用迭代次数: {max_tool_iterations}{Style.RESET_ALL}"
        )
    
    return engine


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
    
    # 测试 InferenceEngine
    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Inference Engine 测试{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
    
    # 注意：这里只是测试配置和基本功能，实际推理需要有效的 API Key
    
    # 测试配置
    config = InferenceConfig(
        model=get_default_model("openai"),
        temperature=0.7,
        system_prompt="你是一个有帮助的助手"
    )
    print(f"创建推理配置: {config.model}, temperature={config.temperature}")
    
    # 测试结果
    result = InferenceResult(
        content="这是一个测试回复",
        raw_response={},
        model=get_default_model("openai"),
        provider="openai",
        usage={"prompt_tokens": 10, "completion_tokens": 5},
        finish_reason="stop"
    )
    print(f"创建推理结果: {result}")
    
    # 测试统计
    print(f"\n{Fore.GREEN}测试完成!{Style.RESET_ALL}\n")
