# 工具调用网关 (ToolCallingGateway) 集成完成

## 变更汇总

将已实现的 [ToolCallingGateway](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/llm_hub/tool_gateway.py#139-628) 集成到实际业务逻辑中，不再只是测试中使用。共修改三处：

---

### 1. [app/llm_hub/inference.py](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/llm_hub/inference.py) — InferenceEngine

```diff:inference.py
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
        model: str = "qwen3-max",
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
        
        logger.info(
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
            logger.info(f"{Fore.BLUE}[{request_id}] 步骤 1/4: 构建 Prompt{Style.RESET_ALL}")
            prompt_messages = self._prompt_builder.build(
                messages=messages,
                system_prompt=config.system_prompt,
                context=config.context,
                tools=config.tools
            )
            
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
            
            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(
                f"{Fore.GREEN}[{request_id}] 推理完成，耗时: {elapsed_ms:.2f}ms{Style.RESET_ALL}"
            )
            
            # 步骤 4: 后处理结果
            logger.info(f"{Fore.BLUE}[{request_id}] 步骤 4/4: 后处理结果{Style.RESET_ALL}")
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
        
        print('模型引擎选择模型config.model:', config.model)
        # 获取模型元数据
        model_metadata = self._model_registry.get_model(config.model)
        print('模型引擎选择模型model_metadata:', model_metadata)
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
                # 如果content是字符串，直接返回
                if isinstance(raw_response["content"], str):
                    return raw_response["content"]      
                blocks = raw_response["content"]
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
        model="qwen3-max",
        temperature=0.7,
        system_prompt="你是一个有帮助的助手"
    )
    print(f"创建推理配置: {config.model}, temperature={config.temperature}")
    
    # 测试结果
    result = InferenceResult(
        content="这是一个测试回复",
        raw_response={},
        model="qwen3-max",
        provider="openai",
        usage={"prompt_tokens": 10, "completion_tokens": 5},
        finish_reason="stop"
    )
    print(f"创建推理结果: {result}")
    
    # 测试统计
    print(f"\n{Fore.GREEN}测试完成!{Style.RESET_ALL}\n")
===
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

# 延迟导入 ToolCallingGateway，避免循环依赖
# 实际使用时通过参数传入已初始化的实例
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.llm_hub.tool_gateway import ToolCallingGateway


class InferenceConfig:
    """
    推理配置
    
    控制推理过程中的各项参数
    """
    
    def __init__(
        self,
        model: str = "qwen3-max",
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
        
        logger.info(
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
        streaming_manager: Optional[StreamingManager] = None,
        tool_gateway: Optional[Any] = None,  # ToolCallingGateway 实例（可选）
        max_tool_iterations: int = 5  # ReAct 循环最大工具调用轮次
    ):
        """
        初始化推理引擎
        
        Args:
            provider: 默认 LLM 供应商实例
            model_registry: 模型注册中心
            prompt_builder: Prompt 构建器（可选，将自动创建）
            streaming_manager: 流式输出管理器（可选，将自动创建）
            tool_gateway: 工具调用网关实例（可选）
                当 LLM 返回 finish_reason=tool_calls 时，
                推理引擎会自动调用网关执行工具并追回结果，
                实现 ReAct（推理→行动→观察）循环。
            max_tool_iterations: ReAct 循环最大工具调用轮次，防止无限循环
        """
        self._provider = provider
        self._model_registry = model_registry
        
        # 初始化 Prompt 构建器
        self._prompt_builder = prompt_builder or PromptBuilder()
        logger.info(f"{Fore.CYAN}初始化 PromptBuilder: {type(self._prompt_builder).__name__}{Style.RESET_ALL}")
        
        # 初始化流式输出管理器
        self._streaming_manager = streaming_manager or StreamingManager()
        logger.info(f"{Fore.CYAN}初始化 StreamingManager: {type(self._streaming_manager).__name__}{Style.RESET_ALL}")
        
        # NOTE: 工具调用网关（Tool Calling Gateway）
        # 作为可选组件注入，使推理引擎具备处理原生 function-calling 的能力
        # 若为 None，则跳过工具调用处理，直接返回 LLM 的原始响应
        self._tool_gateway = tool_gateway
        self._max_tool_iterations = max_tool_iterations
        if tool_gateway is not None:
            logger.info(
                f"{Fore.GREEN}工具调用网关已注入: {type(tool_gateway).__name__}，"
                f"最大工具调用轮次: {max_tool_iterations}{Style.RESET_ALL}"
            )
        else:
            logger.info(
                f"{Fore.YELLOW}工具调用网关未注入，将跳过原生 function-calling 处理{Style.RESET_ALL}"
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
            
            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(
                f"{Fore.GREEN}[{request_id}] 推理完成，耗时: {elapsed_ms:.2f}ms{Style.RESET_ALL}"
            )
            
            # 步骤 4: 处理工具调用（ReAct 循环）
            # NOTE: 如果 LLM 以原生 function-calling 格式要求调用工具
            #       （finish_reason=tool_calls），且注入了工具调用网关，
            #       则自动执行工具并将结果追加到消息列表，再次调用 LLM，
            #       形成 推理→行动→观察 (ReAct) 循环，直到 LLM 给出最终答案为止。
            if (
                self._tool_gateway is not None
                and config.tools  # 本次请求携带了工具定义
                and self._is_tool_call_response(raw_response)  # LLM 要求工具调用
            ):
                logger.info(
                    f"{Fore.BLUE}[{request_id}] 步骤 4/4: 检测到原生工具调用，"
                    f"启动 ReAct 循环（最大 {self._max_tool_iterations} 轮）{Style.RESET_ALL}"
                )
                raw_response, prompt_messages = await self._react_loop(
                    request_id=request_id,
                    provider=provider,
                    provider_config=provider_config,
                    messages=prompt_messages,
                    raw_response=raw_response
                )
            else:
                logger.info(f"{Fore.BLUE}[{request_id}] 步骤 4/4: 后处理结果{Style.RESET_ALL}")
            
            # 步骤 5: 后处理结果
            result = self._postprocess_result(raw_response, config, model_info)
            
            # 记录请求历史
            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
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
    
    def _is_tool_call_response(self, raw_response: Dict[str, Any]) -> bool:
        """
        判断 LLM 响应是否为工具调用请求
        
        支持 OpenAI 格式（finish_reason=tool_calls）
        和 Anthropic 格式（stop_reason=tool_use）
        
        Args:
            raw_response: LLM 原始响应
            
        Returns:
            是否为工具调用响应
        """
        # OpenAI 格式：finish_reason = "tool_calls"
        if "choices" in raw_response:
            try:
                finish_reason = raw_response["choices"][0].get("finish_reason", "")
                if finish_reason == "tool_calls":
                    logger.debug(
                        f"{Fore.CYAN}[工具调用检测] OpenAI 格式，finish_reason=tool_calls{Style.RESET_ALL}"
                    )
                    return True
            except (IndexError, KeyError) as e:
                logger.warning(f"{Fore.YELLOW}[工具调用检测] 解析 choices 失败: {e}{Style.RESET_ALL}")
        
        # Anthropic 格式：stop_reason = "tool_use"
        if raw_response.get("stop_reason") == "tool_use":
            logger.debug(
                f"{Fore.CYAN}[工具调用检测] Anthropic 格式，stop_reason=tool_use{Style.RESET_ALL}"
            )
            return True
        
        return False
    
    async def _react_loop(
        self,
        request_id: str,
        provider: LLMProvider,
        provider_config: Dict[str, Any],
        messages: List[Dict[str, Any]],
        raw_response: Dict[str, Any]
    ) -> tuple:
        """
        ReAct 推理循环：工具调用 → 结果追加 → 再次推理
        
        当 LLM 以原生 function-calling 格式请求工具调用时触发。
        循环逻辑：
          1. 将 LLM 的工具调用请求追加到消息历史（assistant 角色）
          2. 通过 ToolCallingGateway 执行工具
          3. 将执行结果追加到消息历史（tool 角色）
          4. 再次调用 LLM，获取新的响应
          5. 重复直到 LLM 给出最终答案（finish_reason=stop）或达到最大轮次
        
        Args:
            request_id: 请求 ID（用于日志追踪）
            provider: LLM 供应商实例
            provider_config: 供应商配置
            messages: 当前消息列表（会被修改并返回）
            raw_response: 首次推理的原始响应
            
        Returns:
            (最终的 raw_response, 更新后的 messages)
        """
        iteration = 0
        
        while (
            self._is_tool_call_response(raw_response)
            and iteration < self._max_tool_iterations
        ):
            iteration += 1
            logger.info(
                f"{Fore.CYAN}[{request_id}] ══ ReAct 循环 第 {iteration}/{self._max_tool_iterations} 轮 ══{Style.RESET_ALL}"
            )
            
            # ── 步骤 1: 将 LLM 的工具调用消息追加到消息历史 ──────────────
            # 即将助手（assistant）的工具调用请求加入上下文，
            # 保持对话连续性，LLM 后续可知道自己请求了哪些工具。
            assistant_msg = self._extract_assistant_tool_call_message(raw_response)
            if assistant_msg:
                messages.append(assistant_msg)
                logger.debug(
                    f"{Fore.CYAN}[{request_id}] 已追加助手工具调用消息到历史{Style.RESET_ALL}"
                )
            
            # ── 步骤 2: 执行工具调用 ──────────────────────────────────────
            logger.info(
                f"{Fore.BLUE}[{request_id}] 调用 ToolCallingGateway 执行工具{Style.RESET_ALL}"
            )
            tool_results = await self._tool_gateway.execute_tool_calls(
                llm_response=raw_response,
                context={"request_id": request_id, "iteration": iteration}
            )
            
            if not tool_results:
                logger.warning(
                    f"{Fore.YELLOW}[{request_id}] 工具调用网关未返回任何结果，退出循环{Style.RESET_ALL}"
                )
                break
            
            logger.info(
                f"{Fore.GREEN}[{request_id}] 工具执行完成，共 {len(tool_results)} 个结果{Style.RESET_ALL}"
            )
            
            # ── 步骤 3: 将工具执行结果追加到消息历史 ─────────────────────
            # 把工具返回值以 tool 角色消息格式加回消息列表，
            # 这样 LLM 就能读取执行结果并生成最终答案。
            tool_result_msgs = self._tool_gateway.format_results_for_llm(tool_results)
            messages.extend(tool_result_msgs)
            logger.info(
                f"{Fore.BLUE}[{request_id}] 已将 {len(tool_result_msgs)} 条工具结果消息追加到历史{Style.RESET_ALL}"
            )
            
            # ── 步骤 4: 再次调用 LLM 获取新响应 ─────────────────────────
            logger.info(
                f"{Fore.BLUE}[{request_id}] 基于工具结果再次调用 LLM 推理{Style.RESET_ALL}"
            )
            raw_response = await provider.chat(messages, provider_config)
            
            finish_reason = self._extract_finish_reason(raw_response)
            logger.info(
                f"{Fore.GREEN}[{request_id}] 第 {iteration} 轮推理完成，"
                f"finish_reason={finish_reason}{Style.RESET_ALL}"
            )
        
        # 循环结束后记录最终状态
        if iteration >= self._max_tool_iterations and self._is_tool_call_response(raw_response):
            logger.warning(
                f"{Fore.YELLOW}[{request_id}] 已达到最大工具调用轮次 {self._max_tool_iterations}，"
                f"强制返回当前响应{Style.RESET_ALL}"
            )
        else:
            logger.info(
                f"{Fore.GREEN}[{request_id}] ReAct 循环完成，共执行 {iteration} 轮工具调用{Style.RESET_ALL}"
            )
        
        return raw_response, messages
    
    def _extract_assistant_tool_call_message(
        self,
        raw_response: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        从 LLM 响应中提取助手（assistant）工具调用消息
        
        用于将助手消息追加到对话历史，保持上下文连续性。
        支持 OpenAI 格式，提取包含 tool_calls 字段的 assistant message。
        
        Args:
            raw_response: LLM 原始响应
            
        Returns:
            标准格式的助手消息字典，如果无法提取则返回 None
        """
        try:
            # OpenAI 格式：从 choices[0].message 提取
            if "choices" in raw_response and raw_response["choices"]:
                message = raw_response["choices"][0].get("message", {})
                if isinstance(message, dict) and "tool_calls" in message:
                    # 构造标准的 assistant 消息格式
                    assistant_msg = {
                        "role": "assistant",
                        "content": message.get("content"),  # 可能为 None
                        "tool_calls": message["tool_calls"]
                    }
                    logger.debug(
                        f"{Fore.CYAN}提取助手工具调用消息，"
                        f"包含 {len(message['tool_calls'])} 个工具调用{Style.RESET_ALL}"
                    )
                    return assistant_msg
        except Exception as e:
            logger.warning(
                f"{Fore.YELLOW}提取助手工具调用消息失败: {e}{Style.RESET_ALL}"
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
        
        print('模型引擎选择模型config.model:', config.model)
        # 获取模型元数据
        model_metadata = self._model_registry.get_model(config.model)
        print('模型引擎选择模型model_metadata:', model_metadata)
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
                # 如果content是字符串，直接返回
                if isinstance(raw_response["content"], str):
                    return raw_response["content"]      
                blocks = raw_response["content"]
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
        model="qwen3-max",
        temperature=0.7,
        system_prompt="你是一个有帮助的助手"
    )
    print(f"创建推理配置: {config.model}, temperature={config.temperature}")
    
    # 测试结果
    result = InferenceResult(
        content="这是一个测试回复",
        raw_response={},
        model="qwen3-max",
        provider="openai",
        usage={"prompt_tokens": 10, "completion_tokens": 5},
        finish_reason="stop"
    )
    print(f"创建推理结果: {result}")
    
    # 测试统计
    print(f"\n{Fore.GREEN}测试完成!{Style.RESET_ALL}\n")
```

**新增能力：**
- [__init__](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/execution.py#70-92) 新增 `tool_gateway` 和 `max_tool_iterations` 参数（可选，向后兼容）
- 当 LLM 返回 `finish_reason=tool_calls` 时，自动触发 **ReAct 推理循环**，最多 5 轮：
  1. 将助手工具调用消息追回历史
  2. 通过 [ToolCallingGateway](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/llm_hub/tool_gateway.py#139-628) 执行工具
  3. 将工具结果追回历史
  4. 再次调用 LLM 获取新响应
  5. 直到 LLM 给出 `finish_reason=stop` 为止
- 新增三个私有方法：`_is_tool_call_response()`、`_react_loop()`、`_extract_assistant_tool_call_message()`

---

### 2. [app/agents/execution.py](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/execution.py) — ExecutionEngine

```diff:execution.py
"""
执行引擎 (Execution Engine)
================================

本模块负责执行由 Planning Engine 生成的计划。

功能特点：
1. 逐步执行计划中的每个步骤
2. 支持工具调用、技能调用、子 Agent 委派
3. 实现错误处理和恢复机制
4. 收集执行结果

作者: AI Agent Team
创建时间: 2026-02-15
"""

import re
import json as _json
from typing import Dict, List, Any, Optional
from loguru import logger
from colorama import Fore, Style

from app.agents.base import Agent
from app.agents.planning import Plan, PlanStep
from app.tools.hub import ToolHub
from app.skills.manager import SkillManager


class ExecutionResult:
    """执行结果"""
    
    def __init__(
        self,
        success: bool,
        result: Any,
        step_results: List[Dict[str, Any]] = None,
        error: Optional[str] = None
    ):
        """
        初始化执行结果
        
        Args:
            success: 是否成功
            result: 最终结果
            step_results: 每个步骤的执行结果
            error: 错误信息
        """
        self.success = success
        self.result = result
        self.step_results = step_results or []
        self.error = error
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "result": self.result,
            "step_results": self.step_results,
            "error": self.error
        }


class ExecutionEngine:
    """
    执行引擎
    
    执行由 Planning Engine 生成的计划
    """
    
    def __init__(
        self,
        tool_hub: ToolHub,
        skill_manager: SkillManager,
        llm_hub,
        child_agent_manager=None
    ):
        """
        初始化执行引擎
        
        Args:
            tool_hub: 工具中心
            skill_manager: 技能管理器
            llm_hub: LLM Hub 实例
            child_agent_manager: 子 Agent 管理器（可选）
        """
        self.tool_hub = tool_hub
        self.skill_manager = skill_manager
        self.llm_hub = llm_hub
        self.child_agent_manager = child_agent_manager
        
        logger.info(f"{Fore.GREEN}执行引擎初始化完成{Style.RESET_ALL}")
    
    async def execute_plan(
        self,
        agent: Agent,
        plan: Plan,
        context: Optional[Dict[str, Any]] = None
    ) -> ExecutionResult:
        """
        执行计划
        
        Args:
            agent: Agent 实例
            plan: 执行计划
            context: 执行上下文
            
        Returns:
            ExecutionResult: 执行结果
        """
        logger.info(
            f"{Fore.BLUE}开始执行计划，共 {len(plan.steps)} 个步骤{Style.RESET_ALL}"
        )
        
        step_results = []
        final_result = None
        
        try:
            for i, step in enumerate(plan.steps, 1):
                logger.info(
                    f"{Fore.CYAN}执行步骤 {i}/{len(plan.steps)}: "
                    f"action={step.action}{Style.RESET_ALL}"
                )
                
                # 执行步骤（把已完成步骤结果传入，供 skill 等使用）
                step_result = await self._execute_step(agent, step, context, step_results)
                step_results.append(step_result)
                
                # 如果是 final_answer，先合成再返回
                if step.action == "final_answer":
                    template = step.params.get("content", "")
                    
                    # 收集本轮所有成功的工具/技能/委派结果（排除 final_answer 步骤本身）
                    tool_results = [
                        r for r in step_results
                        if r.get("success") and r.get("result")
                        and r.get("action") != "final_answer"
                    ]
                    
                    # 只要有真实数据（工具/技能/委派结果），就调用 LLM 合成最终答案。
                    # LLM 在规划阶段还没有执行结果，final_answer.content 只是意图描述
                    # 或占位符模板，不能直接返回给用户。
                    should_synthesize = bool(tool_results)
                    
                    if should_synthesize:
                        logger.info(
                            f"{Fore.BLUE}[执行引擎] 存在工具/委派执行结果，"
                            f"调用 LLM 合成真实答案...{Style.RESET_ALL}"
                        )
                        final_result = await self._synthesize_answer(
                            agent=agent,
                            task=context.get("task", "") if context else "",
                            tool_results=tool_results,
                            template=template
                        )
                    elif template:
                        final_result = template
                    elif tool_results:
                        # 没有 LLM 合成条件，直接拼接工具结果
                        parts = []
                        for r in tool_results:
                            label = r.get("tool_name") or r.get("agent_id") or r.get("action", "")
                            val = r["result"]
                            if isinstance(val, dict):
                                val = _json.dumps(val, ensure_ascii=False, indent=2)
                            parts.append(f"【{label}】\n{val}")
                        final_result = "\n\n".join(parts)
                    else:
                        final_result = "执行完成，但没有产生具体结果。"

                    logger.info(
                        f"{Fore.GREEN}执行完成，获得最终答案{Style.RESET_ALL}"
                    )
                    break
                
                # 检查步骤是否成功
                if not step_result.get("success", True):
                    logger.warning(
                        f"{Fore.YELLOW}步骤 {i} 执行失败: "
                        f"{step_result.get('error', 'Unknown error')}{Style.RESET_ALL}"
                    )
                    # 继续执行后续步骤（也可以选择中断）
            
            # 如果没有 final_answer，使用最后一个步骤的结果
            if final_result is None and step_results:
                final_result = step_results[-1].get("result", "")
            
            logger.info(f"{Fore.GREEN}计划执行成功{Style.RESET_ALL}")
            
            return ExecutionResult(
                success=True,
                result=final_result,
                step_results=step_results
            )
            
        except Exception as e:
            logger.error(f"{Fore.RED}执行计划时发生错误: {e}{Style.RESET_ALL}")
            
            return ExecutionResult(
                success=False,
                result=None,
                step_results=step_results,
                error=str(e)
            )
    
    async def _synthesize_answer(
        self,
        agent: Agent,
        task: str,
        tool_results: List[Dict[str, Any]],
        template: str = ""
    ) -> str:
        """
        调用 LLM 将工具/技能返回的原始数据合成为自然语言的最终答案。

        在 final_answer 的 content 包含占位符（如 [status]、[customer_name]）
        或为空时触发，避免把模板字符串作为最终结果返回给用户。

        Args:
            agent: 当前执行的 Agent 实例（用于取角色名）
            task: 原始用户任务描述
            tool_results: 本轮所有成功的工具/技能/委派结果列表
            template: LLM 规划时写的 final_answer 模板（可能含占位符）

        Returns:
            str: 基于真实数据合成的自然语言答案
        """
        # ── 格式化工具结果，供 LLM 阅读 ──────────────────────
        result_parts = []
        for idx, r in enumerate(tool_results, 1):
            label = r.get("tool_name") or r.get("agent_id") or r.get("action", f"步骤{idx}")
            val = r.get("result", "")
            if isinstance(val, dict):
                val_str = _json.dumps(val, ensure_ascii=False, indent=2)
            else:
                val_str = str(val)
            # 截断超长输出，防止 token 超限
            if len(val_str) > 3000:
                val_str = val_str[:3000] + "\n...（内容已截断）"
            result_parts.append(f"[来源: {label}]\n{val_str}")

        results_text = "\n\n".join(result_parts)

        synthesis_prompt = f"""你是 {agent.name}，{agent.description}

用户任务：{task}

以下是执行过程中获取到的数据：

{results_text}

请根据以上数据，用清晰、友好的自然语言回答用户的任务需求。
要求：
1. 直接给出具体数据，不要使用 [xxx] 这样的占位符
2. 信息完整，涵盖用户关心的所有字段
3. 格式清晰，必要时使用列表或分段展示
4. 如果数据中有错误或空值，如实告知

请直接输出最终回答，不要包含任何前缀说明。"""

        try:
            from app.llm_hub.inference import InferenceConfig
            config = InferenceConfig(
                model=agent.agent_config.execution_model,
                stream=False,
                temperature=0.3   # 答案合成用低温度，减少幻觉
            )
            response = await self.llm_hub.infer(
                messages=[{"role": "user", "content": synthesis_prompt}],
                config=config
            )
            answer = response.content.strip()
            logger.info(
                f"{Fore.GREEN}[执行引擎] LLM 答案合成完成，"
                f"长度: {len(answer)} 字符{Style.RESET_ALL}"
            )
            return answer

        except Exception as e:
            logger.error(
                f"{Fore.RED}[执行引擎] LLM 答案合成失败，回退到原始数据拼接: {e}{Style.RESET_ALL}"
            )
            # 合成失败时降级：把原始工具结果直接拼接返回
            return "\n\n".join(
                f"【{r.get('tool_name') or r.get('action', '')}】\n"
                + (_json.dumps(r["result"], ensure_ascii=False, indent=2)
                   if isinstance(r["result"], dict) else str(r["result"]))
                for r in tool_results
                if r.get("result")
            ) or template or "执行完成，但未能生成最终答案。"

    async def _execute_step(
        self,
        agent: Agent,
        step: PlanStep,
        context: Optional[Dict[str, Any]] = None,
        prev_results: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        执行单个步骤

        Args:
            agent: Agent 实例
            step: 计划步骤
            context: 执行上下文
            prev_results: 本轮已完成步骤的结果列表，供 skill 等引用真实数据

        Returns:
            Dict[str, Any]: 步骤执行结果
        """
        try:
            if step.action == "tool":
                return await self._execute_tool(step, agent)
            elif step.action == "skill":
                return await self._execute_skill(step, context, agent, prev_results)
            elif step.action == "delegate":
                return await self._delegate_to_agent(step)
            elif step.action == "final_answer":
                return {
                    "success": True,
                    "result": step.params.get("content", ""),
                    "action": "final_answer"
                }
            else:
                # ── 兜底兼容：LLM 有时把工具名直接写成 action（如 "database_query"）
                # 检查 action 值是否是已注册的工具名，若是则自动修正为 action="tool"
                if self.tool_hub and self.tool_hub.get_tool(step.action):
                    original_action = step.action
                    logger.warning(
                        f"{Fore.YELLOW}[兼容] LLM 将工具名 '{original_action}' "
                        f"误用为 action 类型，自动修正为 action='tool'{Style.RESET_ALL}"
                    )
                    # 若 params 中没有 tool_name 则补充（有的话直接用）
                    if "tool_name" not in step.params:
                        step.params["tool_name"] = original_action
                    step.action = "tool"
                    return await self._execute_tool(step, agent)
                
                logger.warning(
                    f"{Fore.YELLOW}未知的 action 类型: {step.action}{Style.RESET_ALL}"
                )
                return {
                    "success": False,
                    "error": f"未知的 action 类型: {step.action}"
                }
                
        except Exception as e:
            logger.error(
                f"{Fore.RED}执行步骤时发生错误 (action={step.action}): {e}{Style.RESET_ALL}"
            )
            return {
                "success": False,
                "error": str(e),
                "action": step.action
            }
    
    async def _execute_tool(
        self, step: PlanStep, agent: Optional[Agent] = None
    ) -> Dict[str, Any]:
        """
        执行工具调用

        Args:
            step: 计划步骤
            agent: 当前 Agent 实例（用于授权校验）

        Returns:
            Dict[str, Any]: 执行结果
        """
        tool_name = step.params.get("tool_name")
        params = step.params.get("params", {})
        
        logger.info(f"{Fore.CYAN}调用工具: {tool_name}{Style.RESET_ALL}")

        # ── 工具授权校验 ──────────────────────────────────────────
        # 若 agent 声明了 available_tools（非空），则只允许使用授权内的工具
        if agent and agent.available_tools and tool_name not in agent.available_tools:
            error_msg = (
                f"Agent '{agent.name}' 无权使用工具 '{tool_name}'。"
                f"该 Agent 仅授权以下工具: {agent.available_tools}。"
                f"如需使用 '{tool_name}'，请委派给有该工具权限的子 Agent。"
            )
            logger.warning(f"{Fore.YELLOW}[权限拦截] {error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": error_msg,
                "action": "tool",
                "tool_name": tool_name
            }
        
        # 获取工具
        tool = self.tool_hub.get_tool(tool_name)
        if not tool:
            error_msg = f"工具不存在: {tool_name}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": error_msg,
                "action": "tool",
                "tool_name": tool_name
            }
        
        # 执行工具
        try:
            result = await tool.execute(params)
            logger.info(f"{Fore.GREEN}工具 {tool_name} 执行成功{Style.RESET_ALL}")
            
            return {
                "success": True,
                "result": result,
                "action": "tool",
                "tool_name": tool_name
            }
        except Exception as e:
            error_msg = f"工具 {tool_name} 执行失败: {e}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": str(e),
                "action": "tool",
                "tool_name": tool_name
            }
    
    async def _execute_skill(
        self,
        step: PlanStep,
        context: Optional[Dict[str, Any]] = None,
        agent: Optional[Agent] = None,
        prev_results: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        执行技能调用

        Args:
            step: 计划步骤
            context: 执行上下文
            agent: 当前 Agent 实例
            prev_results: 本轮已完成步骤的结果列表，用于向 skill 注入真实数据

        Returns:
            Dict[str, Any]: 执行结果
        """
        skill_id = step.params.get("skill_id")
        params = step.params.get("params", {})
        
        logger.info(f"{Fore.CYAN}调用技能: {skill_id}{Style.RESET_ALL}")
        
        # 获取技能
        skill = self.skill_manager.get_skill(skill_id)
        if not skill:
            error_msg = f"技能不存在: {skill_id}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": error_msg,
                "action": "skill",
                "skill_id": skill_id
            }
        
        # 执行技能（通过 LLM）
        try:
            # 1. 准备参数，添加默认值以增强鲁棒性
            safe_params = params.copy()
            
            # ── 将前序步骤的真实数据注入 skill 参数 ────────────────
            # LLM 在规划阶段无法知道工具结果，skill 的 data/content 往往是描述文字。
            # 如果存在真实的工具/委派执行结果，用它们替换或补充 skill 的数据输入。
            if prev_results:
                real_data_parts = []
                for r in prev_results:
                    if not (r.get("success") and r.get("result")):
                        continue
                    label = r.get("tool_name") or r.get("agent_id") or r.get("action", "")
                    val = r["result"]
                    if isinstance(val, dict):
                        val_str = _json.dumps(val, ensure_ascii=False, indent=2)
                    else:
                        val_str = str(val)
                    if len(val_str) > 2000:
                        val_str = val_str[:2000] + "\n...（已截断）"
                    real_data_parts.append(f"[{label}]\n{val_str}")
                
                if real_data_parts:
                    injected_data = "\n\n".join(real_data_parts)
                    # 对于需要数据输入的技能（data_analysis 等），用真实数据替换描述
                    if skill_id in ("data_analysis",):
                        safe_params["data"] = injected_data
                        logger.info(
                            f"{Fore.BLUE}[执行引擎] 向技能 {skill_id} 注入前序步骤真实数据"
                            f"（{len(real_data_parts)} 条）{Style.RESET_ALL}"
                        )
                    # 通用：若参数里有 content/topic 是简短描述，也追加真实数据
                    for key in ("content", "topic", "input"):
                        if key in safe_params and isinstance(safe_params[key], str):
                            if len(safe_params[key]) < 200:  # 短描述，不是真实数据
                                safe_params[key] = safe_params[key] + "\n\n" + injected_data
                                break
            
            # 通用回退逻辑：如果缺 topic 用 content，反之亦然
            if "topic" not in safe_params and "content" in safe_params:
                safe_params["topic"] = safe_params["content"]
            if "content" not in safe_params and "topic" in safe_params:
                safe_params["content"] = safe_params["topic"]
                
            # 针对 text_writing 技能的特定默认值
            if skill_id == "text_writing":
                if "topic" not in safe_params:
                    safe_params["topic"] = "未指定主题"
                if "content_type" not in safe_params:
                    safe_params["content_type"] = "一般文本"
                if "style" not in safe_params:
                    safe_params["style"] = "清晰自然"
                if "word_count" not in safe_params:
                    safe_params["word_count"] = "适中"

            # 2. 构建 Prompt
            try:
                prompt = skill.prompt_template.format(**safe_params)
            except KeyError as e:
                logger.warning(
                    f"{Fore.YELLOW}技能 Prompt 格式化缺少参数: {e}，使用通用 Prompt{Style.RESET_ALL}"
                )
                # 兜底 Prompt
                prompt_params_str = "\n".join([f"{k}: {v}" for k, v in params.items()])
                prompt = f"""请执行技能"{skill.name}"的任务。
                
任务描述:
{skill.description}

输入参数:
{prompt_params_str}

请直接输出执行结果。
"""
            
            from app.llm_hub.inference import InferenceConfig
            
            # 优先使用 agent 配置的模型，否则回退到默认
            model = "gpt-3.5-turbo"
            if agent and agent.agent_config:
                model = agent.agent_config.execution_model
                
            config = InferenceConfig(
                model=model,
                temperature=0.7
            )
            
            response = await self.llm_hub.infer(
                messages=[{"role": "user", "content": prompt}],
                config=config
            )
            
            logger.info(f"{Fore.GREEN}技能 {skill_id} 执行成功{Style.RESET_ALL}")
            
            return {
                "success": True,
                "result": response.content,
                "action": "skill",
                "skill_id": skill_id
            }
            
        except Exception as e:
            error_msg = f"技能 {skill_id} 执行失败: {e}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": str(e),
                "action": "skill",
                "skill_id": skill_id
            }
    
    async def _delegate_to_agent(self, step: PlanStep) -> Dict[str, Any]:
        """
        委派给子 Agent
        
        Args:
            step: 计划步骤
            
        Returns:
            Dict[str, Any]: 执行结果
        """
        agent_id = step.params.get("agent_id")
        task = step.params.get("task")
        
        logger.info(f"{Fore.CYAN}委派任务给子 Agent: {agent_id}{Style.RESET_ALL}")
        
        if not self.child_agent_manager:
            error_msg = "子 Agent 管理器未初始化"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": error_msg,
                "action": "delegate",
                "agent_id": agent_id
            }
        
        # 委派任务（parent_agent_id 设为 None，因为在执行引擎层面不跟踪父 Agent）
        try:
            result = await self.child_agent_manager.delegate_task(
                parent_agent_id=None,  # 添加缺失的参数
                child_agent_id=agent_id,
                task=task
            )
            
            logger.info(
                f"{Fore.GREEN}子 Agent {agent_id} 任务执行完成{Style.RESET_ALL}"
            )
            
            return {
                "success": True,
                "result": result,
                "action": "delegate",
                "agent_id": agent_id
            }
            
        except Exception as e:
            error_msg = f"委派给 Agent {agent_id} 失败: {e}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": str(e),
                "action": "delegate",
                "agent_id": agent_id
            }


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Execution Engine 测试{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
    
    # 测试执行结果
    result = ExecutionResult(
        success=True,
        result="测试成功",
        step_results=[{"action": "tool", "result": "ok"}]
    )
    print(f"创建执行结果: {result.to_dict()}")
    
    print(f"\n{Fore.GREEN}测试完成!{Style.RESET_ALL}\n")
===
"""
执行引擎 (Execution Engine)
================================

本模块负责执行由 Planning Engine 生成的计划。

功能特点：
1. 逐步执行计划中的每个步骤
2. 支持工具调用、技能调用、子 Agent 委派
3. 实现错误处理和恢复机制
4. 收集执行结果

作者: AI Agent Team
创建时间: 2026-02-15
"""

import re
import json as _json
from typing import Dict, List, Any, Optional
from loguru import logger
from colorama import Fore, Style

from app.agents.base import Agent
from app.agents.planning import Plan, PlanStep
from app.tools.hub import ToolHub
from app.skills.manager import SkillManager
# NOTE: ToolCallingGateway 使用 Optional[Any] 类型提示避免循环导入
# 实际在运行时由依赖注入层传入已初始化的实例


class ExecutionResult:
    """执行结果"""
    
    def __init__(
        self,
        success: bool,
        result: Any,
        step_results: List[Dict[str, Any]] = None,
        error: Optional[str] = None
    ):
        """
        初始化执行结果
        
        Args:
            success: 是否成功
            result: 最终结果
            step_results: 每个步骤的执行结果
            error: 错误信息
        """
        self.success = success
        self.result = result
        self.step_results = step_results or []
        self.error = error
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "result": self.result,
            "step_results": self.step_results,
            "error": self.error
        }


class ExecutionEngine:
    """
    执行引擎
    
    执行由 Planning Engine 生成的计划
    """
    
    def __init__(
        self,
        tool_hub: ToolHub,
        skill_manager: SkillManager,
        llm_hub,
        child_agent_manager=None,
        tool_gateway=None  # ToolCallingGateway 实例（可选）
    ):
        """
        初始化执行引擎
        
        Args:
            tool_hub: 工具中心
            skill_manager: 技能管理器
            llm_hub: LLM Hub 实例
            child_agent_manager: 子 Agent 管理器（可选）
            tool_gateway: 工具调用网关实例（可选）
                若提供此参数， _execute_tool() 将优先通过网关执行工具调用，
                从而获得参数验证、超时控制和执行统计能力。
                若未提供，则保持原有直接调用行为（向后兼容）。
        """
        self.tool_hub = tool_hub
        self.skill_manager = skill_manager
        self.llm_hub = llm_hub
        self.child_agent_manager = child_agent_manager
        
        # NOTE: 工具调用网关作为可选依赖注入
        # 当存在时，执行工具调用时优先经由网关，获得参数验证、超时控制和统计记录等增强能力
        # 当不存在时，回退到直接调用 tool.execute()模式
        self.tool_gateway = tool_gateway
        
        if tool_gateway is not None:
            logger.info(
                f"{Fore.GREEN}执行引擎初始化完成，工具调用网关已注入："
                f"{type(tool_gateway).__name__}{Style.RESET_ALL}"
            )
        else:
            logger.info(
                f"{Fore.GREEN}执行引擎初始化完成（无工具调用网关，直接模式）{Style.RESET_ALL}"
            )
    
    async def execute_plan(
        self,
        agent: Agent,
        plan: Plan,
        context: Optional[Dict[str, Any]] = None
    ) -> ExecutionResult:
        """
        执行计划
        
        Args:
            agent: Agent 实例
            plan: 执行计划
            context: 执行上下文
            
        Returns:
            ExecutionResult: 执行结果
        """
        logger.info(
            f"{Fore.BLUE}开始执行计划，共 {len(plan.steps)} 个步骤{Style.RESET_ALL}"
        )
        
        step_results = []
        final_result = None
        
        try:
            for i, step in enumerate(plan.steps, 1):
                logger.info(
                    f"{Fore.CYAN}执行步骤 {i}/{len(plan.steps)}: "
                    f"action={step.action}{Style.RESET_ALL}"
                )
                
                # 执行步骤（把已完成步骤结果传入，供 skill 等使用）
                step_result = await self._execute_step(agent, step, context, step_results)
                step_results.append(step_result)
                
                # 如果是 final_answer，先合成再返回
                if step.action == "final_answer":
                    template = step.params.get("content", "")
                    
                    # 收集本轮所有成功的工具/技能/委派结果（排除 final_answer 步骤本身）
                    tool_results = [
                        r for r in step_results
                        if r.get("success") and r.get("result")
                        and r.get("action") != "final_answer"
                    ]
                    
                    # 只要有真实数据（工具/技能/委派结果），就调用 LLM 合成最终答案。
                    # LLM 在规划阶段还没有执行结果，final_answer.content 只是意图描述
                    # 或占位符模板，不能直接返回给用户。
                    should_synthesize = bool(tool_results)
                    
                    if should_synthesize:
                        logger.info(
                            f"{Fore.BLUE}[执行引擎] 存在工具/委派执行结果，"
                            f"调用 LLM 合成真实答案...{Style.RESET_ALL}"
                        )
                        final_result = await self._synthesize_answer(
                            agent=agent,
                            task=context.get("task", "") if context else "",
                            tool_results=tool_results,
                            template=template
                        )
                    elif template:
                        final_result = template
                    elif tool_results:
                        # 没有 LLM 合成条件，直接拼接工具结果
                        parts = []
                        for r in tool_results:
                            label = r.get("tool_name") or r.get("agent_id") or r.get("action", "")
                            val = r["result"]
                            if isinstance(val, dict):
                                val = _json.dumps(val, ensure_ascii=False, indent=2)
                            parts.append(f"【{label}】\n{val}")
                        final_result = "\n\n".join(parts)
                    else:
                        final_result = "执行完成，但没有产生具体结果。"

                    logger.info(
                        f"{Fore.GREEN}执行完成，获得最终答案{Style.RESET_ALL}"
                    )
                    break
                
                # 检查步骤是否成功
                if not step_result.get("success", True):
                    logger.warning(
                        f"{Fore.YELLOW}步骤 {i} 执行失败: "
                        f"{step_result.get('error', 'Unknown error')}{Style.RESET_ALL}"
                    )
                    # 继续执行后续步骤（也可以选择中断）
            
            # 如果没有 final_answer，使用最后一个步骤的结果
            if final_result is None and step_results:
                final_result = step_results[-1].get("result", "")
            
            logger.info(f"{Fore.GREEN}计划执行成功{Style.RESET_ALL}")
            
            return ExecutionResult(
                success=True,
                result=final_result,
                step_results=step_results
            )
            
        except Exception as e:
            logger.error(f"{Fore.RED}执行计划时发生错误: {e}{Style.RESET_ALL}")
            
            return ExecutionResult(
                success=False,
                result=None,
                step_results=step_results,
                error=str(e)
            )
    
    async def _synthesize_answer(
        self,
        agent: Agent,
        task: str,
        tool_results: List[Dict[str, Any]],
        template: str = ""
    ) -> str:
        """
        调用 LLM 将工具/技能返回的原始数据合成为自然语言的最终答案。

        在 final_answer 的 content 包含占位符（如 [status]、[customer_name]）
        或为空时触发，避免把模板字符串作为最终结果返回给用户。

        Args:
            agent: 当前执行的 Agent 实例（用于取角色名）
            task: 原始用户任务描述
            tool_results: 本轮所有成功的工具/技能/委派结果列表
            template: LLM 规划时写的 final_answer 模板（可能含占位符）

        Returns:
            str: 基于真实数据合成的自然语言答案
        """
        # ── 格式化工具结果，供 LLM 阅读 ──────────────────────
        result_parts = []
        for idx, r in enumerate(tool_results, 1):
            label = r.get("tool_name") or r.get("agent_id") or r.get("action", f"步骤{idx}")
            val = r.get("result", "")
            if isinstance(val, dict):
                val_str = _json.dumps(val, ensure_ascii=False, indent=2)
            else:
                val_str = str(val)
            # 截断超长输出，防止 token 超限
            if len(val_str) > 3000:
                val_str = val_str[:3000] + "\n...（内容已截断）"
            result_parts.append(f"[来源: {label}]\n{val_str}")

        results_text = "\n\n".join(result_parts)

        synthesis_prompt = f"""你是 {agent.name}，{agent.description}

用户任务：{task}

以下是执行过程中获取到的数据：

{results_text}

请根据以上数据，用清晰、友好的自然语言回答用户的任务需求。
要求：
1. 直接给出具体数据，不要使用 [xxx] 这样的占位符
2. 信息完整，涵盖用户关心的所有字段
3. 格式清晰，必要时使用列表或分段展示
4. 如果数据中有错误或空值，如实告知

请直接输出最终回答，不要包含任何前缀说明。"""

        try:
            from app.llm_hub.inference import InferenceConfig
            config = InferenceConfig(
                model=agent.agent_config.execution_model,
                stream=False,
                temperature=0.3   # 答案合成用低温度，减少幻觉
            )
            response = await self.llm_hub.infer(
                messages=[{"role": "user", "content": synthesis_prompt}],
                config=config
            )
            answer = response.content.strip()
            logger.info(
                f"{Fore.GREEN}[执行引擎] LLM 答案合成完成，"
                f"长度: {len(answer)} 字符{Style.RESET_ALL}"
            )
            return answer

        except Exception as e:
            logger.error(
                f"{Fore.RED}[执行引擎] LLM 答案合成失败，回退到原始数据拼接: {e}{Style.RESET_ALL}"
            )
            # 合成失败时降级：把原始工具结果直接拼接返回
            return "\n\n".join(
                f"【{r.get('tool_name') or r.get('action', '')}】\n"
                + (_json.dumps(r["result"], ensure_ascii=False, indent=2)
                   if isinstance(r["result"], dict) else str(r["result"]))
                for r in tool_results
                if r.get("result")
            ) or template or "执行完成，但未能生成最终答案。"

    async def _execute_step(
        self,
        agent: Agent,
        step: PlanStep,
        context: Optional[Dict[str, Any]] = None,
        prev_results: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        执行单个步骤

        Args:
            agent: Agent 实例
            step: 计划步骤
            context: 执行上下文
            prev_results: 本轮已完成步骤的结果列表，供 skill 等引用真实数据

        Returns:
            Dict[str, Any]: 步骤执行结果
        """
        try:
            if step.action == "tool":
                return await self._execute_tool(step, agent)
            elif step.action == "skill":
                return await self._execute_skill(step, context, agent, prev_results)
            elif step.action == "delegate":
                return await self._delegate_to_agent(step)
            elif step.action == "final_answer":
                return {
                    "success": True,
                    "result": step.params.get("content", ""),
                    "action": "final_answer"
                }
            else:
                # ── 兜底兼容：LLM 有时把工具名直接写成 action（如 "database_query"）
                # 检查 action 值是否是已注册的工具名，若是则自动修正为 action="tool"
                if self.tool_hub and self.tool_hub.get_tool(step.action):
                    original_action = step.action
                    logger.warning(
                        f"{Fore.YELLOW}[兼容] LLM 将工具名 '{original_action}' "
                        f"误用为 action 类型，自动修正为 action='tool'{Style.RESET_ALL}"
                    )
                    # 若 params 中没有 tool_name 则补充（有的话直接用）
                    if "tool_name" not in step.params:
                        step.params["tool_name"] = original_action
                    step.action = "tool"
                    return await self._execute_tool(step, agent)
                
                logger.warning(
                    f"{Fore.YELLOW}未知的 action 类型: {step.action}{Style.RESET_ALL}"
                )
                return {
                    "success": False,
                    "error": f"未知的 action 类型: {step.action}"
                }
                
        except Exception as e:
            logger.error(
                f"{Fore.RED}执行步骤时发生错误 (action={step.action}): {e}{Style.RESET_ALL}"
            )
            return {
                "success": False,
                "error": str(e),
                "action": step.action
            }
    
    async def _execute_tool(
        self, step: PlanStep, agent: Optional[Agent] = None
    ) -> Dict[str, Any]:
        """
        执行工具调用

        首先尝试通过 ToolCallingGateway 执行（具备参数验证、超时控制、统计），
        如果网关未注入则回退到直接调用 tool.execute()（却向后兼容）。

        Args:
            step: 计划步骤
            agent: 当前 Agent 实例（用于授权校验）

        Returns:
            Dict[str, Any]: 执行结果
        """
        tool_name = step.params.get("tool_name")
        params = step.params.get("params", {})
        
        logger.info(f"{Fore.CYAN}调用工具: {tool_name}{Style.RESET_ALL}")

        # ── 工具授权校验 ───────────────────────────────────────
        # 若 agent 声明了 available_tools（非空），则只允许使用授权内的工具
        if agent and agent.available_tools and tool_name not in agent.available_tools:
            error_msg = (
                f"Agent '{agent.name}' 无权使用工具 '{tool_name}'。"
                f"该 Agent 仅授权以下工具: {agent.available_tools}。"
                f"如需使用 '{tool_name}'，请委派给有该工具权限的子 Agent。"
            )
            logger.warning(f"{Fore.YELLOW}[权限拦截] {error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": error_msg,
                "action": "tool",
                "tool_name": tool_name
            }
        
        # ── 模式一: 通过 ToolCallingGateway 执行（推荐）───────────────────
        # 提供参数验证、超时控制、执行统计等能力
        if self.tool_gateway is not None:
            return await self._execute_tool_via_gateway(tool_name, params, step)
        
        # ── 模式二: 直接从 ToolHub 调用（向后兼容）────────────────────
        # 当 tool_gateway 未注入时回退到矩式调用方式
        logger.debug(
            f"{Fore.CYAN}[工具执行] 网关未注入，回退到直接模式：{tool_name}{Style.RESET_ALL}"
        )
        return await self._execute_tool_direct(tool_name, params)
    
    async def _execute_tool_via_gateway(
        self,
        tool_name: str,
        params: Dict[str, Any],
        step: PlanStep
    ) -> Dict[str, Any]:
        """
        通过 ToolCallingGateway 执行工具调用
        
        构造一个 OpenAI 格式的模拟响应，交由网关处理。
        网关提供：
        - 参数验证（类型检查、必填字段校验）
        - 超时控制（默认 30 秒）
        - 执行统计（成功率、耗时等）
        
        Args:
            tool_name: 工具名称
            params: 工具参数
            step: 计划步骤（用于构造前缀调用 ID）
            
        Returns:
            Dict[str, Any]: 执行结果
        """
        import uuid
        # 为此次执行生成唯一调用 ID
        call_id = f"exec-{tool_name}-{uuid.uuid4().hex[:8]}"
        
        logger.info(
            f"{Fore.BLUE}[工具网关模式] 通过 ToolCallingGateway 执行工具: "
            f"{tool_name} (call_id={call_id}){Style.RESET_ALL}"
        )
        
        # NOTE: 构造 OpenAI 格式的模拟 LLM 响应。
        # ToolCallingGateway 支持解析 OpenAI / Anthropic 两种格式，
        # 这里使用 OpenAI 格式因为大多数供应商兼容此格式。
        mock_llm_response = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": _json.dumps(params, ensure_ascii=False)
                        }
                    }]
                },
                "finish_reason": "tool_calls"
            }]
        }
        
        try:
            # 通过网关执行，获得参数验证、超时控制和统计
            tool_results = await self.tool_gateway.execute_tool_calls(
                llm_response=mock_llm_response,
                context={"source": "execution_engine", "tool_name": tool_name}
            )
            
            if not tool_results:
                error_msg = f"工具网关未返回任何结果：{tool_name}"
                logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
                return {
                    "success": False,
                    "error": error_msg,
                    "action": "tool",
                    "tool_name": tool_name
                }
            
            # 取第一个结果（对于单步骤工具调用，只有一个结果）
            result = tool_results[0]
            
            # 将 ToolCallStatus 映射到执行引擎的标准格式
            from app.llm_hub.tool_gateway import ToolCallStatus
            if result.status == ToolCallStatus.SUCCESS:
                logger.info(
                    f"{Fore.GREEN}[工具网关模式] 工具 {tool_name} 执行成功，"
                    f"耗时: {result.execution_time_ms:.2f}ms{Style.RESET_ALL}"
                )
                return {
                    "success": True,
                    "result": result.result,
                    "action": "tool",
                    "tool_name": tool_name,
                    "execution_time_ms": result.execution_time_ms
                }
            else:
                error_msg = result.error or f"工具执行失败: {result.status.value}"
                logger.error(
                    f"{Fore.RED}[工具网关模式] 工具 {tool_name} 执行失败: "
                    f"status={result.status.value}, error={error_msg}{Style.RESET_ALL}"
                )
                return {
                    "success": False,
                    "error": error_msg,
                    "action": "tool",
                    "tool_name": tool_name,
                    "execution_time_ms": result.execution_time_ms
                }
                
        except Exception as e:
            error_msg = f"工具 {tool_name} 过网关执行失败: {e}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            # 网关异常时回退到直接模式
            logger.warning(
                f"{Fore.YELLOW}网关执行出错，回退到直接调用模式: {tool_name}{Style.RESET_ALL}"
            )
            return await self._execute_tool_direct(tool_name, params)
    
    async def _execute_tool_direct(
        self,
        tool_name: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        直接从 ToolHub 调用工具（向后兼容模式）
        
        当 tool_gateway 未注入或出现异常时使用此方法。
        
        Args:
            tool_name: 工具名称
            params: 工具参数
            
        Returns:
            Dict[str, Any]: 执行结果
        """
        # 获取工具
        tool = self.tool_hub.get_tool(tool_name)
        if not tool:
            error_msg = f"工具不存在: {tool_name}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": error_msg,
                "action": "tool",
                "tool_name": tool_name
            }
        
        # 执行工具
        try:
            result = await tool.execute(params)
            logger.info(f"{Fore.GREEN}工具 {tool_name} 执行成功{Style.RESET_ALL}")
            
            return {
                "success": True,
                "result": result,
                "action": "tool",
                "tool_name": tool_name
            }
        except Exception as e:
            error_msg = f"工具 {tool_name} 执行失败: {e}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": str(e),
                "action": "tool",
                "tool_name": tool_name
            }
    
    async def _execute_skill(
        self,
        step: PlanStep,
        context: Optional[Dict[str, Any]] = None,
        agent: Optional[Agent] = None,
        prev_results: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        执行技能调用

        Args:
            step: 计划步骤
            context: 执行上下文
            agent: 当前 Agent 实例
            prev_results: 本轮已完成步骤的结果列表，用于向 skill 注入真实数据

        Returns:
            Dict[str, Any]: 执行结果
        """
        skill_id = step.params.get("skill_id")
        params = step.params.get("params", {})
        
        logger.info(f"{Fore.CYAN}调用技能: {skill_id}{Style.RESET_ALL}")
        
        # 获取技能
        skill = self.skill_manager.get_skill(skill_id)
        if not skill:
            error_msg = f"技能不存在: {skill_id}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": error_msg,
                "action": "skill",
                "skill_id": skill_id
            }
        
        # 执行技能（通过 LLM）
        try:
            # 1. 准备参数，添加默认值以增强鲁棒性
            safe_params = params.copy()
            
            # ── 将前序步骤的真实数据注入 skill 参数 ────────────────
            # LLM 在规划阶段无法知道工具结果，skill 的 data/content 往往是描述文字。
            # 如果存在真实的工具/委派执行结果，用它们替换或补充 skill 的数据输入。
            if prev_results:
                real_data_parts = []
                for r in prev_results:
                    if not (r.get("success") and r.get("result")):
                        continue
                    label = r.get("tool_name") or r.get("agent_id") or r.get("action", "")
                    val = r["result"]
                    if isinstance(val, dict):
                        val_str = _json.dumps(val, ensure_ascii=False, indent=2)
                    else:
                        val_str = str(val)
                    if len(val_str) > 2000:
                        val_str = val_str[:2000] + "\n...（已截断）"
                    real_data_parts.append(f"[{label}]\n{val_str}")
                
                if real_data_parts:
                    injected_data = "\n\n".join(real_data_parts)
                    # 对于需要数据输入的技能（data_analysis 等），用真实数据替换描述
                    if skill_id in ("data_analysis",):
                        safe_params["data"] = injected_data
                        logger.info(
                            f"{Fore.BLUE}[执行引擎] 向技能 {skill_id} 注入前序步骤真实数据"
                            f"（{len(real_data_parts)} 条）{Style.RESET_ALL}"
                        )
                    # 通用：若参数里有 content/topic 是简短描述，也追加真实数据
                    for key in ("content", "topic", "input"):
                        if key in safe_params and isinstance(safe_params[key], str):
                            if len(safe_params[key]) < 200:  # 短描述，不是真实数据
                                safe_params[key] = safe_params[key] + "\n\n" + injected_data
                                break
            
            # 通用回退逻辑：如果缺 topic 用 content，反之亦然
            if "topic" not in safe_params and "content" in safe_params:
                safe_params["topic"] = safe_params["content"]
            if "content" not in safe_params and "topic" in safe_params:
                safe_params["content"] = safe_params["topic"]
                
            # 针对 text_writing 技能的特定默认值
            if skill_id == "text_writing":
                if "topic" not in safe_params:
                    safe_params["topic"] = "未指定主题"
                if "content_type" not in safe_params:
                    safe_params["content_type"] = "一般文本"
                if "style" not in safe_params:
                    safe_params["style"] = "清晰自然"
                if "word_count" not in safe_params:
                    safe_params["word_count"] = "适中"

            # 2. 构建 Prompt
            try:
                prompt = skill.prompt_template.format(**safe_params)
            except KeyError as e:
                logger.warning(
                    f"{Fore.YELLOW}技能 Prompt 格式化缺少参数: {e}，使用通用 Prompt{Style.RESET_ALL}"
                )
                # 兜底 Prompt
                prompt_params_str = "\n".join([f"{k}: {v}" for k, v in params.items()])
                prompt = f"""请执行技能"{skill.name}"的任务。
                
任务描述:
{skill.description}

输入参数:
{prompt_params_str}

请直接输出执行结果。
"""
            
            from app.llm_hub.inference import InferenceConfig
            
            # 优先使用 agent 配置的模型，否则回退到默认
            model = "gpt-3.5-turbo"
            if agent and agent.agent_config:
                model = agent.agent_config.execution_model
                
            config = InferenceConfig(
                model=model,
                temperature=0.7
            )
            
            response = await self.llm_hub.infer(
                messages=[{"role": "user", "content": prompt}],
                config=config
            )
            
            logger.info(f"{Fore.GREEN}技能 {skill_id} 执行成功{Style.RESET_ALL}")
            
            return {
                "success": True,
                "result": response.content,
                "action": "skill",
                "skill_id": skill_id
            }
            
        except Exception as e:
            error_msg = f"技能 {skill_id} 执行失败: {e}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": str(e),
                "action": "skill",
                "skill_id": skill_id
            }
    
    async def _delegate_to_agent(self, step: PlanStep) -> Dict[str, Any]:
        """
        委派给子 Agent
        
        Args:
            step: 计划步骤
            
        Returns:
            Dict[str, Any]: 执行结果
        """
        agent_id = step.params.get("agent_id")
        task = step.params.get("task")
        
        logger.info(f"{Fore.CYAN}委派任务给子 Agent: {agent_id}{Style.RESET_ALL}")
        
        if not self.child_agent_manager:
            error_msg = "子 Agent 管理器未初始化"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": error_msg,
                "action": "delegate",
                "agent_id": agent_id
            }
        
        # 委派任务（parent_agent_id 设为 None，因为在执行引擎层面不跟踪父 Agent）
        try:
            result = await self.child_agent_manager.delegate_task(
                parent_agent_id=None,  # 添加缺失的参数
                child_agent_id=agent_id,
                task=task
            )
            
            logger.info(
                f"{Fore.GREEN}子 Agent {agent_id} 任务执行完成{Style.RESET_ALL}"
            )
            
            return {
                "success": True,
                "result": result,
                "action": "delegate",
                "agent_id": agent_id
            }
            
        except Exception as e:
            error_msg = f"委派给 Agent {agent_id} 失败: {e}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": str(e),
                "action": "delegate",
                "agent_id": agent_id
            }


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Execution Engine 测试{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
    
    # 测试执行结果
    result = ExecutionResult(
        success=True,
        result="测试成功",
        step_results=[{"action": "tool", "result": "ok"}]
    )
    print(f"创建执行结果: {result.to_dict()}")
    
    print(f"\n{Fore.GREEN}测试完成!{Style.RESET_ALL}\n")
```

**新增能力：**
- [__init__](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/execution.py#70-92) 新增 `tool_gateway` 参数（可选，向后兼容）
- [_execute_tool()](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/execution.py#356-422) 升级：优先通过网关执行（参数验证、超时控制、执行统计），网关异常时自动回退到直接调用
- 新增两个私有方法：`_execute_tool_via_gateway()`、`_execute_tool_direct()`

---

### 3. [app/utils/dependencies.py](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/utils/dependencies.py) — 依赖注入层

```diff:dependencies.py
"""
API 依赖注入函数模块 (Dependency Injection Functions)
====================================================

本模块集中管理所有 API 端点的依赖注入函数。
采用懒加载单例模式，确保服务实例在整个应用生命周期内只初始化一次。

设计原则：
  1. 懒加载：首次调用时初始化，后续复用同一个实例
  2. 单例模式：全局共享同一个服务实例，避免重复创建
  3. 统一管理：所有 Depends 依赖注入函数集中在此，便于维护和调试

包含的依赖注入函数：
  1. get_automation_service()    - 自动化服务实例
  2. get_agent_registry()        - Agent 注册表实例
  3. get_agent_executor()        - Agent 执行器实例
  4. get_chat_service()          - 对话服务实例
  5. get_skill_manager()         - 技能管理器实例
  6. get_tool_hub()              - 工具中心实例
  7. get_workflow_engine()       - 工作流引擎实例
  8. get_workflows()             - 工作流字典实例

作者: AI Agent Team
创建时间: 2026-02-25
"""

from loguru import logger
from colorama import Fore, Style

# ============================================================================
# 全局服务实例变量（用于懒加载单例模式）
# ============================================================================

# 自动化服务相关
_automation_service = None

# Agent 相关
_agent_registry = None
_agent_executor = None
_child_agent_manager = None

# 对话服务相关
_chat_service = None

# 技能管理相关
_skill_manager = None

# 工具中心相关
_tool_hub = None

# 工作流相关
_workflow_engine = None
_workflows = {}


# ============================================================================
# 自动化服务依赖注入函数
# ============================================================================

def get_automation_service():
    """
    获取 AutomationService 实例（依赖注入）
    
    懒加载：首次调用时初始化，后续复用同一个实例。
    负责初始化 OpenAI Provider、Model Registry、Inference Engine、ToolHub 和 SkillManager。
    
    Returns:
        AutomationService: 自动化服务实例
    """
    global _automation_service
    if _automation_service is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 AutomationService...{Style.RESET_ALL}")

        from app.llm_hub.providers.openai import OpenAIProvider
        from app.llm_hub.registry import ModelRegistry
        from app.core.config import settings
        from app.llm_hub.inference import InferenceEngine
        from app.tools.hub import ToolHub
        from app.skills.manager import SkillManager
        from app.services.automation_service import AutomationService
        from app.tools.builtin import register_all_builtin_tools
        from app.skills.library import register_all_builtin_skills

        # 创建推理引擎（需要 provider 和 model_registry）
        provider = OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL
        )
        model_registry = ModelRegistry()
        inference_engine = InferenceEngine(
            provider=provider,
            model_registry=model_registry
        )

        # 初始化工具和技能管理器
        tool_hub = ToolHub()
        skill_manager = SkillManager()

        # 注册所有内置工具和技能
        register_all_builtin_tools(tool_hub)
        register_all_builtin_skills(skill_manager)

        # 创建自动化服务
        _automation_service = AutomationService(
            llm_hub=inference_engine,
            tool_hub=tool_hub,
            skill_manager=skill_manager
        )
        logger.info(f"{Fore.GREEN}【依赖注入】AutomationService 初始化完成{Style.RESET_ALL}")

    return _automation_service


# ============================================================================
# Agent 相关依赖注入函数
# ============================================================================

def get_agent_registry():
    """
    获取 AgentRegistry 实例（依赖注入）
    
    负责初始化 Agent 注册表，并注册所有内置 Agent。
    
    Returns:
        AgentRegistry: Agent 注册表实例
    """
    global _agent_registry
    if _agent_registry is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 AgentRegistry...{Style.RESET_ALL}")
        from app.agents.registry import AgentRegistry
        from app.agents.library.customer_service import register_customer_service_agents
        
        _agent_registry = AgentRegistry()
        
        # 注册所有内置 Agent
        register_customer_service_agents(_agent_registry)
        
        logger.info(f"{Fore.GREEN}【依赖注入】AgentRegistry 初始化完成{Style.RESET_ALL}")
    
    return _agent_registry


def get_agent_executor():
    """
    获取 LangGraphAgentExecutor 实例（依赖注入）
    
    同时初始化 ChildAgentManager，使父 Agent 能够将任务委派给子 Agent。
    负责初始化 OpenAI Provider、Model Registry、Inference Engine、ToolHub、SkillManager 等。
    
    Returns:
        LangGraphAgentExecutor: Agent 执行器实例
    """
    global _agent_executor, _child_agent_manager
    if _agent_executor is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 LangGraphAgentExecutor...{Style.RESET_ALL}")
        
        # 导入所需模块
        from app.llm_hub.providers.openai import OpenAIProvider
        from app.llm_hub.registry import ModelRegistry
        from app.core.config import settings
        from app.llm_hub.inference import InferenceEngine
        from app.tools.hub import ToolHub
        from app.skills.manager import SkillManager
        from app.agents.langgraph_executor import LangGraphAgentExecutor
        from app.agents.child_agent_manager import ChildAgentManager
        from app.tools.builtin import register_all_builtin_tools
        from app.skills.library import register_all_builtin_skills
        
        # 创建默认 LLM Provider（使用 OpenAI 兼容接口）
        provider = OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL
        )
        logger.debug(f"{Fore.CYAN}【依赖注入】已创建 OpenAIProvider（base_url={settings.OPENAI_BASE_URL}）{Style.RESET_ALL}")
        
        # 创建模型注册中心
        model_registry = ModelRegistry()
        logger.debug(f"{Fore.CYAN}【依赖注入】已创建 ModelRegistry{Style.RESET_ALL}")
        
        # 创建推理引擎（需要 provider 和 model_registry 两个必填参数）
        inference_engine = InferenceEngine(
            provider=provider,
            model_registry=model_registry
        )
        logger.debug(f"{Fore.CYAN}【依赖注入】已创建 InferenceEngine{Style.RESET_ALL}")
        
        tool_hub = ToolHub()
        skill_manager = SkillManager()
        
        # 注册所有内置工具和技能
        register_all_builtin_tools(tool_hub)
        register_all_builtin_skills(skill_manager)
        
        # 获取 Agent 注册表（确保已初始化）
        agent_registry = get_agent_registry()
        
        # 创建子 Agent 管理器，让父 Agent 能把任务委派给子 Agent
        _child_agent_manager = ChildAgentManager(
            agent_registry=agent_registry,
            llm_hub=inference_engine,
            tool_hub=tool_hub,
            skill_manager=skill_manager
        )
        logger.debug(f"{Fore.CYAN}【依赖注入】已创建 ChildAgentManager，支持多层 Agent 委派{Style.RESET_ALL}")
        
        # 创建执行器，传入子 Agent 管理器
        _agent_executor = LangGraphAgentExecutor(
            llm_hub=inference_engine,
            tool_hub=tool_hub,
            skill_manager=skill_manager,
            child_agent_manager=_child_agent_manager
        )
        
        logger.info(f"{Fore.GREEN}【依赖注入】LangGraphAgentExecutor 初始化完成（含 ChildAgentManager）{Style.RESET_ALL}")
    
    return _agent_executor


# ============================================================================
# 对话服务依赖注入函数
# ============================================================================

def get_chat_service():
    """
    获取 ChatService 实例（依赖注入）
    
    懒加载：首次调用时初始化，后续复用同一个实例。
    负责初始化 OpenAI Provider、Model Registry、Inference Engine 和 ShortTermMemory。
    
    Returns:
        ChatService: 对话服务实例
    """
    global _chat_service
    if _chat_service is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 ChatService...{Style.RESET_ALL}")

        from app.llm_hub.providers.openai import OpenAIProvider
        from app.llm_hub.registry import ModelRegistry
        from app.core.config import settings
        from app.llm_hub.inference import InferenceEngine
        from app.services.chat_service import ChatService
        from app.memory.short_term import ShortTermMemory

        # 创建 LLM Provider（使用 OpenAI 兼容接口）
        provider = OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL
        )
        logger.debug(
            f"{Fore.CYAN}【依赖注入】已创建 OpenAIProvider "
            f"(base_url={settings.OPENAI_BASE_URL}){Style.RESET_ALL}"
        )

        # 创建推理引擎
        model_registry = ModelRegistry()
        inference_engine = InferenceEngine(
            provider=provider,
            model_registry=model_registry
        )

        # 创建短期记忆（最多保留 10 条历史消息）
        memory = ShortTermMemory(max_messages=10)

        # 创建对话服务
        _chat_service = ChatService(llm_hub=inference_engine, memory=memory)
        logger.info(f"{Fore.GREEN}【依赖注入】ChatService 初始化完成{Style.RESET_ALL}")

    return _chat_service


# ============================================================================
# 技能管理依赖注入函数
# ============================================================================

def get_skill_manager():
    """
    获取 SkillManager 实例（依赖注入）
    
    负责初始化技能管理器，并注册所有内置技能。
    
    Returns:
        SkillManager: 技能管理器实例
    """
    global _skill_manager
    if _skill_manager is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 SkillManager...{Style.RESET_ALL}")
        from app.skills.manager import SkillManager
        from app.skills.library import register_all_builtin_skills
        
        _skill_manager = SkillManager()
        
        # 注册所有内置技能
        register_all_builtin_skills(_skill_manager)
        
        logger.info(f"{Fore.GREEN}【依赖注入】SkillManager 初始化完成{Style.RESET_ALL}")
    
    return _skill_manager


# ============================================================================
# 工具中心依赖注入函数
# ============================================================================

def get_tool_hub():
    """
    获取 ToolHub 实例（依赖注入）
    
    负责初始化工具中心，并注册所有内置工具。
    
    Returns:
        ToolHub: 工具中心实例
    """
    global _tool_hub
    if _tool_hub is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 ToolHub...{Style.RESET_ALL}")
        from app.tools.hub import ToolHub
        from app.tools.builtin import register_all_builtin_tools
        
        _tool_hub = ToolHub()
        
        # 注册所有内置工具
        register_all_builtin_tools(_tool_hub)
        
        logger.info(f"{Fore.GREEN}【依赖注入】ToolHub 初始化完成{Style.RESET_ALL}")
    
    return _tool_hub


# ============================================================================
# 工作流相关依赖注入函数
# ============================================================================

def get_workflow_engine():
    """
    获取 WorkflowEngine 实例（依赖注入）
    
    负责初始化工作流引擎。
    
    Returns:
        WorkflowEngine: 工作流引擎实例
    """
    global _workflow_engine
    if _workflow_engine is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 WorkflowEngine...{Style.RESET_ALL}")
        from app.workflows.engine import WorkflowEngine
        
        _workflow_engine = WorkflowEngine()
        logger.info(f"{Fore.GREEN}【依赖注入】WorkflowEngine 初始化完成{Style.RESET_ALL}")
    
    return _workflow_engine


def get_workflows():
    """
    获取所有工作流（依赖注入）
    
    负责加载所有内置工作流定义。
    
    Returns:
        Dict[str, Workflow]: 工作流字典
    """
    global _workflows
    if not _workflows:
        logger.info(f"{Fore.BLUE}【依赖注入】加载工作流定义...{Style.RESET_ALL}")
        
        # 注册所有内置工作流
        from app.workflows.templates.intent_routing import INTENT_ROUTING_WORKFLOW
        _workflows[INTENT_ROUTING_WORKFLOW.workflow_id] = INTENT_ROUTING_WORKFLOW
        
        logger.info(f"{Fore.GREEN}【依赖注入】工作流定义加载完成，共 {len(_workflows)} 个{Style.RESET_ALL}")
    
    return _workflows
===
"""
API 依赖注入函数模块 (Dependency Injection Functions)
====================================================

本模块集中管理所有 API 端点的依赖注入函数。
采用懒加载单例模式，确保服务实例在整个应用生命周期内只初始化一次。

设计原则：
  1. 懒加载：首次调用时初始化，后续复用同一个实例
  2. 单例模式：全局共享同一个服务实例，避免重复创建
  3. 统一管理：所有 Depends 依赖注入函数集中在此，便于维护和调试

包含的依赖注入函数：
  1. get_automation_service()    - 自动化服务实例
  2. get_agent_registry()        - Agent 注册表实例
  3. get_agent_executor()        - Agent 执行器实例
  4. get_chat_service()          - 对话服务实例
  5. get_skill_manager()         - 技能管理器实例
  6. get_tool_hub()              - 工具中心实例
  7. get_workflow_engine()       - 工作流引擎实例
  8. get_workflows()             - 工作流字典实例

作者: AI Agent Team
创建时间: 2026-02-25
"""

from loguru import logger
from colorama import Fore, Style

# ============================================================================
# 全局服务实例变量（用于懒加载单例模式）
# ============================================================================

# 自动化服务相关
_automation_service = None

# Agent 相关
_agent_registry = None
_agent_executor = None
_child_agent_manager = None

# 对话服务相关
_chat_service = None

# 技能管理相关
_skill_manager = None

# 工具中心相关
_tool_hub = None

# 工具调用网关相关
# NOTE: 工具调用网关全局单例，供 Agent 执行引擎和推理引擎共享使用
_tool_gateway = None

# 工作流相关
_workflow_engine = None
_workflows = {}


# ============================================================================
# 自动化服务依赖注入函数
# ============================================================================

def get_automation_service():
    """
    获取 AutomationService 实例（依赖注入）
    
    懒加载：首次调用时初始化，后续复用同一个实例。
    负责初始化 OpenAI Provider、Model Registry、Inference Engine、ToolHub、SkillManager。
    
    Returns:
        AutomationService: 自动化服务实例
    """
    global _automation_service
    if _automation_service is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 AutomationService...{Style.RESET_ALL}")

        from app.llm_hub.providers.openai import OpenAIProvider
        from app.llm_hub.registry import ModelRegistry
        from app.core.config import settings
        from app.llm_hub.inference import InferenceEngine
        from app.tools.hub import ToolHub
        from app.skills.manager import SkillManager
        from app.services.automation_service import AutomationService
        from app.tools.builtin import register_all_builtin_tools
        from app.skills.library import register_all_builtin_skills

        # 创建推理引擎（需要 provider 和 model_registry）
        provider = OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL
        )
        model_registry = ModelRegistry()
        
        # 初始化工具和技能管理器
        tool_hub = ToolHub()
        skill_manager = SkillManager()

        # 注册所有内置工具和技能
        register_all_builtin_tools(tool_hub)
        register_all_builtin_skills(skill_manager)
        
        # 初始化工具调用网关（AutomationService 共享全局单例）
        # NOTE: 自动化服务经常需要调用工具，
        #       网关提供参数验证、超时控制和统计自动化工具调用
        tool_gateway_instance = get_tool_gateway(tool_hub)
        logger.debug(f"{Fore.CYAN}【依赖注入】AutomationService 使用工具调用网关: " \
                     f"{type(tool_gateway_instance).__name__}{Style.RESET_ALL}")
        
        inference_engine = InferenceEngine(
            provider=provider,
            model_registry=model_registry,
            tool_gateway=tool_gateway_instance  # 注入工具调用网关
        )

        # 创建自动化服务
        _automation_service = AutomationService(
            llm_hub=inference_engine,
            tool_hub=tool_hub,
            skill_manager=skill_manager
        )
        logger.info(f"{Fore.GREEN}【依赖注入】AutomationService 初始化完成{Style.RESET_ALL}")

    return _automation_service


# ============================================================================
# Agent 相关依赖注入函数
# ============================================================================

def get_agent_registry():
    """
    获取 AgentRegistry 实例（依赖注入）
    
    负责初始化 Agent 注册表，并注册所有内置 Agent。
    
    Returns:
        AgentRegistry: Agent 注册表实例
    """
    global _agent_registry
    if _agent_registry is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 AgentRegistry...{Style.RESET_ALL}")
        from app.agents.registry import AgentRegistry
        from app.agents.library.customer_service import register_customer_service_agents
        
        _agent_registry = AgentRegistry()
        
        # 注册所有内置 Agent
        register_customer_service_agents(_agent_registry)
        
        logger.info(f"{Fore.GREEN}【依赖注入】AgentRegistry 初始化完成{Style.RESET_ALL}")
    
    return _agent_registry


def get_agent_executor():
    """
    获取 LangGraphAgentExecutor 实例（依赖注入）
    
    同时初始化 ChildAgentManager，使父 Agent 能够将任务委派给子 Agent。
    负责初始化 OpenAI Provider、Model Registry、Inference Engine、ToolHub、SkillManager 等。
    
    Returns:
        LangGraphAgentExecutor: Agent 执行器实例
    """
    global _agent_executor, _child_agent_manager
    if _agent_executor is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 LangGraphAgentExecutor...{Style.RESET_ALL}")
        
        # 导入所需模块
        from app.llm_hub.providers.openai import OpenAIProvider
        from app.llm_hub.registry import ModelRegistry
        from app.core.config import settings
        from app.llm_hub.inference import InferenceEngine
        from app.tools.hub import ToolHub
        from app.skills.manager import SkillManager
        from app.agents.langgraph_executor import LangGraphAgentExecutor
        from app.agents.child_agent_manager import ChildAgentManager
        from app.tools.builtin import register_all_builtin_tools
        from app.skills.library import register_all_builtin_skills
        
        # 创建默认 LLM Provider（使用 OpenAI 兼容接口）
        provider = OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL
        )
        logger.debug(f"{Fore.CYAN}【依赖注入】已创建 OpenAIProvider（base_url={settings.OPENAI_BASE_URL}）{Style.RESET_ALL}")
        
        # 创建模型注册中心
        model_registry = ModelRegistry()
        logger.debug(f"{Fore.CYAN}【依赖注入】已创建 ModelRegistry{Style.RESET_ALL}")
        
        tool_hub = ToolHub()
        skill_manager = SkillManager()
        
        # 注册所有内置工具和技能
        register_all_builtin_tools(tool_hub)
        register_all_builtin_skills(skill_manager)
        
        # ── 初始化工具调用网关（Agent 核心组件）─────────────────────────────
        # ToolCallingGateway 将 ToolHub 中的工具同步进去，提供：
        # 1. 参数验证（类型检查、必填字段）
        # 2. 超时控制（默认 30 秒）
        # 3. 执行统计（成功率、耗时）
        # 4. ReAct 循环支持（工具结果追回 LLM 推理）
        tool_gateway_instance = get_tool_gateway(tool_hub)
        logger.debug(
            f"{Fore.CYAN}【依赖注入】工具调用网关已初始化: "
            f"{type(tool_gateway_instance).__name__}{Style.RESET_ALL}"
        )
        
        # 创建推理引擎（注入工具调用网关，支持原生 function-calling ReAct 循环）
        inference_engine = InferenceEngine(
            provider=provider,
            model_registry=model_registry,
            tool_gateway=tool_gateway_instance  # 将网关注入推理引擎
        )
        logger.debug(f"{Fore.CYAN}【依赖注入】已创建 InferenceEngine（含工具调用网关）{Style.RESET_ALL}")
        
        # 获取 Agent 注册表（确保已初始化）
        agent_registry = get_agent_registry()
        
        # 创建子 Agent 管理器，让父 Agent 能把任务委派给子 Agent
        _child_agent_manager = ChildAgentManager(
            agent_registry=agent_registry,
            llm_hub=inference_engine,
            tool_hub=tool_hub,
            skill_manager=skill_manager
        )
        logger.debug(f"{Fore.CYAN}【依赖注入】已创建 ChildAgentManager，支持多层 Agent 委派{Style.RESET_ALL}")
        
        # 创建执行器，传入子 Agent 管理器和工具调用网关
        from app.agents.execution import ExecutionEngine
        execution_engine = ExecutionEngine(
            tool_hub=tool_hub,
            skill_manager=skill_manager,
            llm_hub=inference_engine,
            child_agent_manager=_child_agent_manager,
            tool_gateway=tool_gateway_instance  # 将网关注入执行引擎
        )
        logger.debug(f"{Fore.CYAN}【依赖注入】已创建 ExecutionEngine（含工具调用网关）{Style.RESET_ALL}")
        
        # NOTE: LangGraphAgentExecutor 内部会自己创建 ExecutionEngine，
        #       这里我们需要覆盖它的内部 execution_engine。
        #       此外射1 层内置的 LangGraphAgentExecutor 进行次级处理。
        _agent_executor = LangGraphAgentExecutor(
            llm_hub=inference_engine,
            tool_hub=tool_hub,
            skill_manager=skill_manager,
            child_agent_manager=_child_agent_manager
        )
        # 将已注入工具调用网关的 execution_engine 替换内部的
        # NOTE: 这里直接替换 LangGraphAgentExecutor 内部的 execution_engine
        #       确保工具调用网关能在实际 Agent 执行过程中生效
        _agent_executor.execution_engine = execution_engine
        logger.debug(
            f"{Fore.CYAN}【依赖注入】已将含工具调用网关的 ExecutionEngine "
            f"注入到 LangGraphAgentExecutor{Style.RESET_ALL}"
        )
        
        logger.info(f"{Fore.GREEN}【依赖注入】LangGraphAgentExecutor 初始化完成（含 ChildAgentManager + ToolCallingGateway）{Style.RESET_ALL}")
    
    return _agent_executor


# ============================================================================
# 对话服务依赖注入函数
# ============================================================================

def get_chat_service():
    """
    获取 ChatService 实例（依赖注入）
    
    懒加载：首次调用时初始化，后续复用同一个实例。
    负责初始化 OpenAI Provider、Model Registry、Inference Engine 和 ShortTermMemory。
    
    Returns:
        ChatService: 对话服务实例
    """
    global _chat_service
    if _chat_service is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 ChatService...{Style.RESET_ALL}")

        from app.llm_hub.providers.openai import OpenAIProvider
        from app.llm_hub.registry import ModelRegistry
        from app.core.config import settings
        from app.llm_hub.inference import InferenceEngine
        from app.services.chat_service import ChatService
        from app.memory.short_term import ShortTermMemory

        # 创建 LLM Provider（使用 OpenAI 兼容接口）
        provider = OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL
        )
        logger.debug(
            f"{Fore.CYAN}【依赖注入】已创建 OpenAIProvider "
            f"(base_url={settings.OPENAI_BASE_URL}){Style.RESET_ALL}"
        )

        # 创建推理引擎
        model_registry = ModelRegistry()
        inference_engine = InferenceEngine(
            provider=provider,
            model_registry=model_registry
        )

        # 创建短期记忆（最多保留 10 条历史消息）
        memory = ShortTermMemory(max_messages=10)

        # 创建对话服务
        _chat_service = ChatService(llm_hub=inference_engine, memory=memory)
        logger.info(f"{Fore.GREEN}【依赖注入】ChatService 初始化完成{Style.RESET_ALL}")

    return _chat_service


# ============================================================================
# 技能管理依赖注入函数
# ============================================================================

def get_skill_manager():
    """
    获取 SkillManager 实例（依赖注入）
    
    负责初始化技能管理器，并注册所有内置技能。
    
    Returns:
        SkillManager: 技能管理器实例
    """
    global _skill_manager
    if _skill_manager is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 SkillManager...{Style.RESET_ALL}")
        from app.skills.manager import SkillManager
        from app.skills.library import register_all_builtin_skills
        
        _skill_manager = SkillManager()
        
        # 注册所有内置技能
        register_all_builtin_skills(_skill_manager)
        
        logger.info(f"{Fore.GREEN}【依赖注入】SkillManager 初始化完成{Style.RESET_ALL}")
    
    return _skill_manager


# ============================================================================
# 工具中心依赖注入函数
# ============================================================================

def get_tool_hub():
    """
    获取 ToolHub 实例（依赖注入）
    
    负责初始化工具中心，并注册所有内置工具。
    
    Returns:
        ToolHub: 工具中心实例
    """
    global _tool_hub
    if _tool_hub is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 ToolHub...{Style.RESET_ALL}")
        from app.tools.hub import ToolHub
        from app.tools.builtin import register_all_builtin_tools
        
        _tool_hub = ToolHub()
        
        # 注册所有内置工具
        register_all_builtin_tools(_tool_hub)
        
        logger.info(f"{Fore.GREEN}【依赖注入】ToolHub 初始化完成{Style.RESET_ALL}")
    
    return _tool_hub


# ============================================================================
# 工具调用网关依赖注入函数
# ============================================================================

def get_tool_gateway(tool_hub_instance=None):
    """
    获取 ToolCallingGateway 实例（依赖注入）
    
    懒加载单例模式：首次调用时初始化，后续复用同一个实例。
    
    初始化时会将 tool_hub_instance 中的所有工具同步注册到网关中，
    使网关具备参数验证、超时控制和执行统计能力。
    
    Args:
        tool_hub_instance: ToolHub 实例（如果提供，则将其中工具同步到网关）
            如果为 None，使用全局 ToolHub 实例或创建一个空网关
        
    Returns:
        ToolCallingGateway: 工具调用网关实例
    """
    global _tool_gateway
    if _tool_gateway is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 ToolCallingGateway...{Style.RESET_ALL}")
        from app.llm_hub.tool_gateway import ToolCallingGateway
        
        # 创建工具调用网关实例
        _tool_gateway = ToolCallingGateway()
        
        # 确定要同步的 ToolHub
        hub = tool_hub_instance or (_tool_hub if _tool_hub else None)
        
        if hub is not None:
            # 将 ToolHub 中已注册的工具同步到工具调用网关
            # NOTE: 工具调用网关有自己的注册表，用于参数验证和执行
            #       ToolHub 是工具的权威来源（供 Agent 规划时展示 Schema）
            #       ToolCallingGateway 是工具执行的代理（增强验证、超时、统计能力）
            tools = hub.list_tools()
            synced_count = 0
            for tool in tools:
                # 从 ToolSchema 中提取 JSON Schema （用于网关的参数验证）
                tool_schema = tool.schema
                schema_dict = {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
                if hasattr(tool_schema, "parameters") and tool_schema.parameters:
                    params_def = tool_schema.parameters
                    if isinstance(params_def, dict):
                        schema_dict = params_def
                
                _tool_gateway.register_tool(
                    name=tool.name,
                    tool_instance=tool,
                    schema=schema_dict
                )
                synced_count += 1
            
            logger.info(
                f"{Fore.GREEN}【依赖注入】已将 {synced_count} 个工具从 ToolHub 同步到 ToolCallingGateway{Style.RESET_ALL}"
            )
        else:
            logger.warning(
                f"{Fore.YELLOW}【依赖注入】初始化 ToolCallingGateway 时未提供 ToolHub，"
                f"工具将在首次调用时手动注册。"
                f"建议在 get_agent_executor() 中通过 get_tool_gateway(tool_hub) 初始化{Style.RESET_ALL}"
            )
        
        logger.info(f"{Fore.GREEN}【依赖注入】ToolCallingGateway 初始化完成{Style.RESET_ALL}")
    
    return _tool_gateway


# ============================================================================
# 工作流相关依赖注入函数
# ============================================================================

def get_workflow_engine():
    """
    获取 WorkflowEngine 实例（依赖注入）
    
    负责初始化工作流引擎。
    
    Returns:
        WorkflowEngine: 工作流引擎实例
    """
    global _workflow_engine
    if _workflow_engine is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 WorkflowEngine...{Style.RESET_ALL}")
        from app.workflows.engine import WorkflowEngine
        
        _workflow_engine = WorkflowEngine()
        logger.info(f"{Fore.GREEN}【依赖注入】WorkflowEngine 初始化完成{Style.RESET_ALL}")
    
    return _workflow_engine


def get_workflows():
    """
    获取所有工作流（依赖注入）
    
    负责加载所有内置工作流定义。
    
    Returns:
        Dict[str, Workflow]: 工作流字典
    """
    global _workflows
    if not _workflows:
        logger.info(f"{Fore.BLUE}【依赖注入】加载工作流定义...{Style.RESET_ALL}")
        
        # 注册所有内置工作流
        from app.workflows.templates.intent_routing import INTENT_ROUTING_WORKFLOW
        _workflows[INTENT_ROUTING_WORKFLOW.workflow_id] = INTENT_ROUTING_WORKFLOW
        
        logger.info(f"{Fore.GREEN}【依赖注入】工作流定义加载完成，共 {len(_workflows)} 个{Style.RESET_ALL}")
    
    return _workflows
```

**新增能力：**
- 新增全局变量 `_tool_gateway`、新增函数 `get_tool_gateway(tool_hub_instance=None)`
- `get_tool_gateway()` 初始化时将 [ToolHub](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/tools/hub.py#7-44) 中的 8 个内置工具自动同步到网关（含参数 Schema）
- [get_agent_executor()](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/utils/dependencies.py#143-217) 和 [get_automation_service()](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/utils/dependencies.py#60-112) 均注入 `tool_gateway_instance` 到 [InferenceEngine](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/llm_hub/inference.py#118-582) 和 [ExecutionEngine](file:///Users/yuye/YeahWork/AI%20Agent%20%E9%A1%B9%E7%9B%AE/ai-agent/app/agents/execution.py#63-624)

---

## 数据流（集成后）

```
┌─────────────────────────────────────────────────────────┐
│                   依赖注入层 (Startup)                     │
│  get_tool_hub() → ToolHub (8 tools)                     │
│  get_tool_gateway(tool_hub) → ToolCallingGateway        │
│    └─ 同步注册 8 个工具 (含参数 Schema)                   │
└──────────────────────────┬──────────────────────────────┘
                           │ 注入
          ┌────────────────┴──────────────────┐
          ▼                                   ▼
  InferenceEngine                    ExecutionEngine
  (tool_gateway 注入)                (tool_gateway 注入)
          │                                   │
          │ LLM 返回 tool_calls               │ _execute_tool() 被调用
          ▼                                   ▼
    _react_loop()                  _execute_tool_via_gateway()
    ├─ _tool_gateway.execute_tool_calls()       │
    ├─ format_results_for_llm()                 └─ tool_gateway.execute_tool_calls()
    └─ 再次调用 provider.chat()                     (参数验证 + 超时控制 + 统计)
```

---

## 测试结果

```
tests/unit/test_tool_gateway.py  33 passed ✅
tests/unit/ (全部)              292 passed ✅  11 failed*
```

> [!NOTE]
> 11 个失败均为**回归前既已存在**的问题（已通过 `git stash` 双重验证），与本次修改无关：
> - `test_default_config`：测试期望默认模型 `gpt-3.5-turbo`，代码实际默认为 `qwen3-max`（历史不一致）
> - `test_execution_engine_execute_tool`：Mock LLM 答案合成覆盖了测试期望值（历史问题）
> - 其余 9 个类似，均为模型/配置不一致的历史问题

## 依赖注入层验证截图（日志）

集成后首次启动时，日志输出如下：

```
【依赖注入】初始化 ToolCallingGateway...
注册工具: search, 参数模式: ['query', 'max_results']
注册工具: http_request, 参数模式: ['method', 'url', ...]
注册工具: python_executor, 参数模式: ['code', 'timeout']
注册工具: file_read, 参数模式: ['path', 'encoding', 'max_size']
注册工具: file_write, 参数模式: ['path', 'content', ...]
注册工具: database_query, 参数模式: ['query', 'params', ...]
注册工具: calculator, 参数模式: ['expression', 'precision', 'degrees']
注册工具: datetime, 参数模式: ['operation', 'datetime', ...]
【依赖注入】已将 8 个工具从 ToolHub 同步到 ToolCallingGateway ✅
网关工具数量: 8
统计信息: {'total_calls': 0, 'successful_calls': 0, 'failed_calls': 0, ...}
```
