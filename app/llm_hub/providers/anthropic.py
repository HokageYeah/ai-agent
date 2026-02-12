"""
Anthropic 供应商适配器 (Anthropic Provider)
==========================================

本模块实现了 Anthropic 的 LLM 供应商适配器，用于与 Claude API 进行交互。

功能特点：
1. 支持 Claude-3 系列模型（Opus、Sonnet、Haiku）
2. 提供非流式和流式对话接口
3. 完整的错误处理和日志记录
4. 支持 Claude 特有的 system prompt 格式

支持的模型：
- claude-3-opus-20240229
- claude-3-sonnet-20240229
- claude-3-haiku-20240307

与 OpenAI 的差异：
1. System prompt 需要单独传递，不在 messages 数组中
2. 使用 max_tokens 而不是 max_output_tokens
3. 响应格式略有不同

作者: AI Agent Team
创建时间: 2026-02-12
"""

import os
from typing import AsyncIterator, List, Dict, Any, Optional
from anthropic import AsyncAnthropic
from loguru import logger
from colorama import Fore, Style
from app.llm_hub.providers.base import LLMProvider


class AnthropicProvider(LLMProvider):
    """
    Anthropic 供应商适配器
    
    继承自 LLMProvider 抽象基类，实现与 Anthropic Claude API 的交互。
    提供了 chat（对话）、stream（流式对话）两个核心方法。
    
    注意: Anthropic 官方 API 目前不直接支持 embeddings。
    
    使用方法:
        provider = AnthropicProvider(api_key="your-api-key")
        response = await provider.chat(messages, config)
    """
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        """
        初始化 Anthropic 供应商适配器
        
        初始化方法会从环境变量或传入参数中获取 API Key，
        并创建异步客户端实例。
        
        Args:
            api_key: Anthropic API Key，如果为 None 则从环境变量 ANTHROPIC_API_KEY 读取
            base_url: Anthropic API 的基础 URL，可选，用于自定义端点
        """
        # 获取 API Key
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        # 获取基础 URL
        self.base_url = base_url or os.getenv("ANTHROPIC_BASE_URL")
        
        # 打印初始化日志
        logger.info(
            f"{Fore.CYAN}初始化 Anthropic 供应商适配器，"
            f"基础URL: {self.base_url}{Style.RESET_ALL}"
        )
        
        # 检查 API Key 是否配置
        if not self.api_key:
            logger.warning(
                f"{Fore.YELLOW}警告: ANTHROPIC_API_KEY 未设置，"
                f"Anthropic 供应商适配器可能无法正常工作。{Style.RESET_ALL}"
            )
        
        # 创建异步客户端
        self.client = AsyncAnthropic(
            api_key=self.api_key,
            base_url=self.base_url
        )
        
        logger.debug(f"{Fore.BLUE}Anthropic 异步客户端创建完成{Style.RESET_ALL}")
    
    async def chat(
        self,
        messages: List[Dict[str, str]],
        config: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        非流式对话接口
        
        发送对话请求到 Anthropic API，获取完整的响应结果。
        
        与 OpenAI 的区别：
        1. System prompt 需要单独提取，通过 system 参数传递
        2. 使用 max_tokens 控制最大输出长度
        3. 响应格式中 stop_reason 的含义略有不同
        
        Args:
            messages: 对话消息列表，格式为 [{"role": "user", "content": "你好"}]
                     支持的角色包括: system, user, assistant
            config: 配置字典，可包含以下键值:
                    - model: 模型名称，默认为 "claude-3-opus-20240229"
                    - temperature: 温度参数，控制随机性，默认为 0.7
                    - max_tokens: 最大输出 token 数，默认为 4096
                    - 其他 Anthropic API 支持的参数
        
        Returns:
            Anthropic API 响应的字典格式，包含:
            - id: 响应 ID
            - type: 响应类型 (message)
            - role: 角色 (assistant)
            - content: 回复内容块列表
            - stop_reason: 停止原因 (end_turn, max_tokens, stop_sequence)
            - usage: Token 使用统计
        
        Raises:
            AnthropicError: API 调用失败时抛出异常
        
        Example:
            ```python
            messages = [
                {"role": "system", "content": "你是一个有趣的助手"},
                {"role": "user", "content": "给我讲个笑话"}
            ]
            config = {"model": "claude-3-sonnet-20240229", "temperature": 0.7}
            response = await provider.chat(messages, config)
            ```
        """
        config = config or {}
        
        # 从配置中获取模型，默认为 Claude-3 Opus
        model = config.get("model", "claude-3-opus-20240229")
        # 获取温度参数
        temperature = config.get("temperature", 0.7)
        # 获取最大输出 token 数
        max_tokens = config.get("max_tokens", 4096)
        
        logger.info(
            f"{Fore.BLUE}发送对话请求到 Anthropic，"
            f"模型: {model}, 温度: {temperature}, "
            f"最大Token: {max_tokens}, 消息数: {len(messages)}{Style.RESET_ALL}"
        )
        
        # 处理消息格式
        # Anthropic 使用单独的 system 参数，不在 messages 数组中
        system_prompt = None
        filtered_messages = []
        
        for msg in messages:
            if msg["role"] == "system":
                # 提取 system prompt
                system_prompt = msg["content"]
            else:
                # 保留 user 和 assistant 消息
                filtered_messages.append(msg)
        
        try:
            # 构建请求参数
            request_params = {
                "model": model,
                "messages": filtered_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                # 过滤掉不需要的参数
                **{k: v for k, v in config.items()
                   if k not in ["model", "temperature", "max_tokens", "stream"]}
            }
            
            # 如果有 system prompt，添加到请求中
            if system_prompt:
                request_params["system"] = system_prompt
                logger.debug(
                    f"{Fore.BLUE}检测到 system prompt，长度: {len(system_prompt)} 字符{Style.RESET_ALL}"
                )
            
            # 调用 Anthropic API
            response = await self.client.messages.create(**request_params)
            
            logger.info(
                f"{Fore.GREEN}Anthropic 对话响应成功，"
                f"响应ID: {response.id}, "
                f"停止原因: {response.stop_reason}, "
                f"内容块数: {len(response.content)}{Style.RESET_ALL}"
            )
            
            # 将响应转换为字典格式返回
            return response.model_dump()
            
        except Exception as e:
            logger.error(
                f"{Fore.RED}Anthropic 对话请求失败: {e}{Style.RESET_ALL}"
            )
            raise
    
    async def stream(
        self,
        messages: List[Dict[str, str]],
        config: Dict[str, Any] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        流式对话接口
        
        发送对话请求到 Anthropic API，以流式方式逐步返回响应。
        
        Anthropic 流式响应的事件类型：
        - message_start: 消息开始
        - content_block_start: 内容块开始
        - content_block_delta: 内容块增量（包含实际文本）
        - content_block_stop: 内容块结束
        - message_delta: 消息增量（包含 usage）
        - message_stop: 消息结束
        
        Args:
            messages: 对话消息列表，格式同 chat 方法
            config: 配置字典，同 chat 方法
        
        Yields:
            流式响应事件，每个事件是一个字典，包含:
            - type: 事件类型
            - id: 响应 ID
            - delta: 增量内容（对于 content_block_delta 事件）
        
        Raises:
            AnthropicError: API 调用失败时抛出异常
        
        Example:
            ```python
            messages = [{"role": "user", "content": "写一首诗"}]
            async for event in provider.stream(messages):
                if event["type"] == "content_block_delta":
                    print(event["delta"]["text"], end="", flush=True)
            ```
        """
        config = config or {}
        
        # 获取配置参数
        model = config.get("model", "claude-3-opus-20240229")
        temperature = config.get("temperature", 0.7)
        max_tokens = config.get("max_tokens", 4096)
        
        logger.info(
            f"{Fore.BLUE}开始流式对话请求到 Anthropic，"
            f"模型: {model}, 消息数: {len(messages)}{Style.RESET_ALL}"
        )
        
        # 处理消息格式
        system_prompt = None
        filtered_messages = []
        
        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            else:
                filtered_messages.append(msg)
        
        try:
            # 构建请求参数
            request_params = {
                "model": model,
                "messages": filtered_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,  # 启用流式模式
                # 过滤参数
                **{k: v for k, v in config.items()
                   if k not in ["model", "temperature", "max_tokens", "stream"]}
            }
            
            # 添加 system prompt
            if system_prompt:
                request_params["system"] = system_prompt
            
            # 发起流式请求
            stream = await self.client.messages.create(**request_params)
            
            # 处理流式事件
            async for event in stream:
                # 将事件对象转换为字典
                # Anthropic 的事件对象可能有 model_dump 方法
                if hasattr(event, "model_dump"):
                    yield event.model_dump()
                else:
                    # 回退到 __dict__
                    yield event.__dict__
            
            logger.info(
                f"{Fore.GREEN}Anthropic 流式对话完成{Style.RESET_ALL}"
            )
            
        except Exception as e:
            logger.error(
                f"{Fore.RED}Anthropic 流式请求失败: {e}{Style.RESET_ALL}"
            )
            raise
    
    async def embeddings(
        self,
        texts: List[str],
        model: str = None
    ) -> List[List[float]]:
        """
        文本向量化接口（暂未支持）
        
        Anthropic 官方 API 目前不直接提供文本嵌入（Embeddings）功能。
        建议使用其他专门的嵌入服务，如 Voyage AI、OpenAI Embeddings 等。
        
        Args:
            texts: 要向量化的文本列表
            model: 嵌入模型名称（此参数被忽略）
        
        Returns:
            不会返回，正常抛出 NotImplementedError
        
        Raises:
            NotImplementedError: 总是抛出此异常
        
        Note:
            替代方案:
            1. 使用 OpenAI 的 text-embedding-3-small 或 text-embedding-3-large
            2. 使用 Voyage AI 的嵌入模型
            3. 使用 Cohere 的 Embed API
        """
        logger.warning(
            f"{Fore.YELLOW}警告: Anthropic 官方 API 目前不支持 embeddings 功能。"
            f"建议使用 OpenAI 或其他嵌入服务。{Style.RESET_ALL}"
        )
        
        raise NotImplementedError(
            "Anthropic 供应商目前不支持 embeddings 功能。\n"
            "建议替代方案:\n"
            "1. 使用 OpenAIProvider 的 embeddings 方法\n"
            "2. 集成 Voyage AI、Cohere 等专门的嵌入服务"
        )


# =============================================================================
# 测试代码
# =============================================================================

async def _test_anthropic_provider():
    """异步测试函数"""
    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Anthropic Provider 测试{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
    
    # 测试初始化
    provider = AnthropicProvider()
    print(f"创建 AnthropicProvider 实例: {type(provider).__name__}")
    
    # 测试 embeddings 方法（预期抛出异常）
    print(f"\n{Fore.YELLOW}测试 embeddings 方法（预期抛出 NotImplementedError）:{Style.RESET_ALL}")
    try:
        await provider.embeddings(["测试文本"])
    except NotImplementedError as e:
        print(f"正确抛出异常: {e}")
    
    print(f"\n{Fore.GREEN}测试完成!{Style.RESET_ALL}\n")


if __name__ == "__main__":
    import asyncio
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
    
    # 运行异步测试
    asyncio.run(_test_anthropic_provider())
