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
from typing import Dict, List, Any, Optional, AsyncIterator
from loguru import logger
from colorama import Fore, Style, Back
from datetime import datetime

# 导入 LLM Hub 内部模块
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
        model: str = "gpt-3.5-turbo",
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
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.stream = stream
        self.system_prompt = system_prompt
        self.context = context or []
        self.tools = tools or []
        self.provider = provider
        
        logger.debug(
            f"{Fore.BLUE}创建推理配置: model={model}, stream={stream}, "
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
        streaming_manager: Optional[StreamingManager] = None
    ):
        """
        初始化推理引擎
        
        Args:
            provider: 默认 LLM 供应商实例
            model_registry: 模型注册中心
            prompt_builder: Prompt 构建器（可选，将自动创建）
            streaming_manager: 流式输出管理器（可选，将自动创建）
        """
        self._provider = provider
        self._model_registry = model_registry
        
        # 初始化 Prompt 构建器
        self._prompt_builder = prompt_builder or PromptBuilder()
        logger.info(f"{Fore.CYAN}初始化 PromptBuilder: {type(self._prompt_builder).__name__}{Style.RESET_ALL}")
        
        # 初始化流式输出管理器
        self._streaming_manager = streaming_manager or StreamingManager()
        logger.info(f"{Fore.CYAN}初始化 StreamingManager: {type(self._streaming_manager).__name__}{Style.RESET_ALL}")
        
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
            logger.debug(f"{Fore.BLUE}[{request_id}] 步骤 1/4: 构建 Prompt{Style.RESET_ALL}")
            prompt_messages = self._prompt_builder.build(
                messages=messages,
                system_prompt=config.system_prompt,
                context=config.context,
                tools=config.tools
            )
            
            # 步骤 2: 选择模型和供应商
            logger.debug(f"{Fore.BLUE}[{request_id}] 步骤 2/4: 选择模型{Style.RESET_ALL}")
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
            logger.debug(f"{Fore.BLUE}[{request_id}] 步骤 3/4: 执行推理 (供应商: {type(provider).__name__}){Style.RESET_ALL}")
            start_time = datetime.now()
            
            raw_response = await provider.chat(prompt_messages, provider_config)
            
            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(
                f"{Fore.GREEN}[{request_id}] 推理完成，耗时: {elapsed_ms:.2f}ms{Style.RESET_ALL}"
            )
            
            # 步骤 4: 后处理结果
            logger.debug(f"{Fore.BLUE}[{request_id}] 步骤 4/4: 后处理结果{Style.RESET_ALL}")
            result = self._postprocess_result(raw_response, config, model_info)
            
            # 记录请求历史
            self._record_request(request_id, config, result, elapsed_ms)
            
            logger.info(
                f"{Fore.GREEN}[{request_id}] 推理请求成功完成，结果长度: {len(result.content)} 字符{Style.RESET_ALL}"
            )
            
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
        
        # 获取模型元数据
        model_metadata = self._model_registry.get_model(config.model)
        
        if model_metadata is None:
            logger.warning(
                f"{Fore.YELLOW}模型 {config.model} 未在注册中心找到，使用默认模型{Style.RESET_ALL}"
            )
            # 返回一个默认的模型元数据
            model_metadata = ModelMetadata(
                model_id=config.model,
                provider=type(provider).__name__.lower(),
                model_name=config.model,
                capabilities=["chat"],
                context_window=4096,
                max_output_tokens=4096
            )
        
        logger.debug(
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
        
        logger.debug(
            f"{Fore.BLUE}后处理完成: content_len={len(content)}, "
            f"finish_reason={finish_reason}{Style.RESET_ALL}"
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
            # OpenAI 格式
            if "choices" in raw_response:
                choice = raw_response["choices"][0]
                if "message" in choice:
                    return choice["message"].get("content", "")
                elif "delta" in choice:
                    return choice["delta"].get("content", "")
            
            # Anthropic 格式
            if "content" in raw_response:
                blocks = raw_response["content"]
                for block in blocks:
                    if block.get("type") == "text":
                        return block.get("text", "")
            
            # 其他格式，尝试通用提取
            return str(raw_response)
            
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
            统计信息字典
        """
        return {
            "total_requests": self._request_count,
            "successful_requests": self._request_count - self._error_count,
            "failed_requests": self._error_count,
            "error_rate": self._error_count / max(1, self._request_count),
            "provider": type(self._provider).__name__
        }
    
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
    model_registry: Any
) -> InferenceEngine:
    """
    创建推理引擎实例的便捷函数
    
    Args:
        provider: LLM 供应商实例
        model_registry: 模型注册中心
        
    Returns:
        新的 InferenceEngine 实例
    """
    return InferenceEngine(
        provider=provider,
        model_registry=model_registry
    )


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
        model="gpt-3.5-turbo",
        temperature=0.7,
        system_prompt="你是一个有帮助的助手"
    )
    print(f"创建推理配置: {config.model}, temperature={config.temperature}")
    
    # 测试结果
    result = InferenceResult(
        content="这是一个测试回复",
        raw_response={},
        model="gpt-3.5-turbo",
        provider="openai",
        usage={"prompt_tokens": 10, "completion_tokens": 5},
        finish_reason="stop"
    )
    print(f"创建推理结果: {result}")
    
    # 测试统计
    print(f"\n{Fore.GREEN}测试完成!{Style.RESET_ALL}\n")
