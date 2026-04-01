"""
OpenAI 供应商适配器 (OpenAI Provider)
=====================================

本模块实现了 OpenAI 的 LLM 供应商适配器，用于与 OpenAI API 进行交互。

功能特点：
1. 支持 GPT-4、GPT-3.5-turbo 等模型
2. 提供非流式和流式对话接口
3. 支持文本向量化（Embeddings）
4. 完整的错误处理和日志记录

支持的模型：
- gpt-4
- gpt-4-turbo
- gpt-3.5-turbo
- text-embedding-3-small
- text-embedding-3-large

作者: AI Agent Team
创建时间: 2026-02-12
"""

import os
import asyncio
from typing import AsyncIterator, List, Dict, Any, Optional
import httpx
from openai import AsyncOpenAI
from loguru import logger
from colorama import Fore, Style
from app.core.config import get_default_model
from app.llm_hub.providers.base import LLMProvider

# NOTE: 429 限流自动重试配置
# 最多重试次数，每次退避时间翻倍（2→4→8→16 秒），避免频繁触发限流
_MAX_RETRY_TIMES = 4
_INITIAL_WAIT_SECONDS = 2
_MAX_EMPTY_RESPONSE_RETRY_TIMES = 2
_INITIAL_EMPTY_RESPONSE_WAIT_SECONDS = 1


class OpenAIProvider(LLMProvider):
    """
    OpenAI 供应商适配器
    
    继承自 LLMProvider 抽象基类，实现与 OpenAI API 的交互。
    提供了 chat（对话）、stream（流式对话）和 embeddings（向量化）三个核心方法。
    
    使用方法:
        provider = OpenAIProvider(api_key="your-api-key")
        response = await provider.chat(messages, config)
    """
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        """
        初始化 OpenAI 供应商适配器
        
        初始化方法会从环境变量或传入参数中获取 API Key，
        并创建异步客户端实例。
        
        Args:
            api_key: OpenAI API Key，如果为 None 则从环境变量 OPENAI_API_KEY 读取
            base_url: OpenAI API 的基础 URL，可选，用于自定义端点
        """
        # 获取 API Key，优先使用传入的参数，其次使用环境变量
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        # 获取基础 URL，优先使用传入的参数，其次使用环境变量
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        
        # 打印初始化日志（出于安全考虑，不打印 API Key）
        logger.info(
            f"{Fore.CYAN}初始化 OpenAI 供应商适配器，"
            f"基础URL: {self.base_url}{Style.RESET_ALL}"
        )
        
        # 检查 API Key 是否配置
        if not self.api_key:
            logger.warning(
                f"{Fore.YELLOW}警告: OPENAI_API_KEY 未设置，"
                f"OpenAI 供应商适配器可能无法正常工作。{Style.RESET_ALL}"
            )
        
        # 创建异步客户端
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
        
        logger.debug(f"{Fore.BLUE}OpenAI 异步客户端创建完成{Style.RESET_ALL}")

    @staticmethod
    def _extract_response_error_detail(response: Any) -> tuple[Optional[Any], Optional[str], Optional[Dict[str, Any]]]:
        """
        统一提取第三方响应里的错误元数据。

        设计原因：
        - 不同代理/OpenAI 兼容网关在失败时返回的字段不完全一致；
        - 需要在公共层判断“这是明确错误”还是“瞬时空白响应”，避免把瞬时抖动直接升级成规划失败。
        """
        status_code = getattr(response, "status", None)
        error_msg = getattr(response, "msg", None) or getattr(response, "error", None)
        base_resp = getattr(response, "base_resp", None)
        if isinstance(base_resp, dict):
            if status_code is None:
                status_code = base_resp.get("status_code")
            if not error_msg:
                error_msg = base_resp.get("status_msg") or base_resp.get("error")
        return status_code, error_msg, base_resp if isinstance(base_resp, dict) else None

    @classmethod
    def _should_retry_empty_response(
        cls,
        response: Any,
        *,
        attempt: int,
    ) -> bool:
        """
        判断当前“空回复”是否属于可自动重试的瞬时异常。

        设计原则：
        - 仅对“没有 choices，且也没有明确错误码/错误消息”的空白响应做短退避重试；
        - 有明确错误信息时立即失败，避免掩盖真实配置/权限/模型问题。
        """
        if attempt > _MAX_EMPTY_RESPONSE_RETRY_TIMES:
            return False

        status_code, error_msg, _ = cls._extract_response_error_detail(response)
        has_explicit_error = (
            (status_code not in (None, 0, "0"))
            or bool(str(error_msg or "").strip())
        )
        return not has_explicit_error
    
    async def chat(
        self,
        messages: List[Dict[str, str]],
        config: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        非流式对话接口
        
        发送对话请求到 OpenAI API，获取完整的响应结果。
        
        Args:
            messages: 对话消息列表，格式为 [{"role": "user", "content": "你好"}]
                     支持的角色包括: system, user, assistant
            config: 配置字典，可包含以下键值:
                    - model: 模型名称，默认为 "gpt-3.5-turbo"
                    - temperature: 温度参数，控制随机性，默认为 0.7
                    - max_tokens: 最大输出 token 数
                    - 其他 OpenAI API 支持的参数
        
        Returns:
            OpenAI API 响应的字典格式，包含:
            - id: 响应 ID
            - object: 对象类型
            - created: 创建时间戳
            - model: 使用的模型
            - choices: 回复选项列表
            - usage: Token 使用统计
        
        Raises:
            OpenAIError: API 调用失败时抛出异常
        
        Example:
            ```python
            messages = [
                {"role": "system", "content": "你是一个有帮助的助手"},
                {"role": "user", "content": "你好"}
            ]
            config = {"model": "gpt-4", "temperature": 0.7}
            response = await provider.chat(messages, config)
            ```
        """
        config = config or {}
        
        # 从项目统一配置中获取默认模型，避免 Provider 层继续保留历史硬编码值
        model = config.get("model") or get_default_model("openai")
        # 获取温度参数，控制输出的随机性
        temperature = config.get("temperature", 0.7)
        
        logger.info(
            f"{Fore.BLUE}发送对话请求到 OpenAI，"
            f"模型: {model}, 温度: {temperature}, "
            f"消息数: {len(messages)}{Style.RESET_ALL}"
        )
        
        # 过滤掉不需要传递给 API 的参数（model/temperature/stream 单独处理）
        filtered_config = {
            k: v for k, v in config.items()
            if k not in ["model", "temperature", "stream"]
        }

        # NOTE: 针对 429 限流错误进行指数退避重试
        # 当 API 返回 429 时，等待 wait_seconds 后重试，每次等待时间翻倍
        # 最多重试 _MAX_RETRY_TIMES 次，超出后向上层抛出异常
        wait_seconds = _INITIAL_WAIT_SECONDS
        empty_response_wait_seconds = _INITIAL_EMPTY_RESPONSE_WAIT_SECONDS
        for attempt in range(1, _MAX_RETRY_TIMES + 2):  # attempt: 1..5（第5次才真正抛出）
            try:
                # 调用 OpenAI API 创建对话（非流式模式）
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    stream=False,
                    **filtered_config
                )

                # 检查响应是否为空
                if response is None:
                    if attempt <= _MAX_EMPTY_RESPONSE_RETRY_TIMES:
                        logger.warning(
                            f"{Fore.YELLOW}[OpenAI] API 返回空响应，"
                            f"判定为瞬时异常并执行第 {attempt}/{_MAX_EMPTY_RESPONSE_RETRY_TIMES} 次重试，"
                            f"等待 {empty_response_wait_seconds} 秒后继续...{Style.RESET_ALL}"
                        )
                        await asyncio.sleep(empty_response_wait_seconds)
                        empty_response_wait_seconds *= 2
                        continue
                    raise ValueError("API 返回空响应")

                # NOTE: 调试用，记录完整响应体（DEBUG 级别，生产环境可关闭）
                logger.debug(
                    f"{Fore.BLUE}[OpenAI] 原始响应: id={response.id}, "
                    f"model={response.model}, "
                    f"tokens={getattr(response.usage, 'total_tokens', '?')}{Style.RESET_ALL}"
                )

                # 安全获取 choices
                choices = getattr(response, 'choices', None)

                # NOTE: 当 API 返回错误响应时（如 status=435 Model not support），
                #       choices 会是 None。必须抛出异常，不能静默返回，
                #       否则上层（Planning/Reflection）会尝试把错误信息解析为 JSON
                if choices is None or len(choices) == 0:
                    status_code, error_msg, base_resp = self._extract_response_error_detail(response)
                    detail = (
                        f"status={status_code}, msg={error_msg}"
                        if status_code not in (None, "")
                        else str(response)
                    )

                    if self._should_retry_empty_response(response, attempt=attempt):
                        logger.warning(
                            f"{Fore.YELLOW}[OpenAI] 检测到无 choices 的空白响应，"
                            f"缺少明确错误码/错误消息，"
                            f"执行第 {attempt}/{_MAX_EMPTY_RESPONSE_RETRY_TIMES} 次瞬时重试 | "
                            f"base_resp={base_resp}{Style.RESET_ALL}"
                        )
                        await asyncio.sleep(empty_response_wait_seconds)
                        empty_response_wait_seconds *= 2
                        continue

                    logger.error(
                        f"{Fore.RED}API 返回错误，无有效回复内容: {detail}{Style.RESET_ALL}"
                    )
                    raise ValueError(f"API 返回错误，无法获取回复内容: {detail}")

                logger.info(
                    f"{Fore.GREEN}OpenAI 对话响应成功，"
                    f"响应ID: {response.id}{Style.RESET_ALL}"
                )

                # 将响应转换为字典格式返回
                return response.model_dump()

            except httpx.HTTPStatusError as e:
                # NOTE: 只对 429 限流错误进行重试，其他 HTTP 错误直接抛出
                if e.response.status_code == 429 and attempt <= _MAX_RETRY_TIMES:
                    logger.warning(
                        f"{Fore.YELLOW}[OpenAI] 触发限流 (429 Too Many Requests)，"
                        f"第 {attempt}/{_MAX_RETRY_TIMES} 次重试，"
                        f"等待 {wait_seconds} 秒后继续...{Style.RESET_ALL}"
                    )
                    await asyncio.sleep(wait_seconds)
                    # 指数退避：等待时间翻倍
                    wait_seconds *= 2
                    continue
                # 非 429 错误或已超出最大重试次数，向上抛出
                logger.error(
                    f"{Fore.RED}OpenAI 对话请求失败 (HTTP {e.response.status_code}): {e}{Style.RESET_ALL}"
                )
                raise

            except Exception as e:
                logger.error(
                    f"{Fore.RED}OpenAI 对话请求失败: {type(e).__name__}: {e}{Style.RESET_ALL}"
                )
                raise
    
    async def stream(
        self,
        messages: List[Dict[str, str]],
        config: Dict[str, Any] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        流式对话接口
        
        发送对话请求到 OpenAI API，以流式方式逐步返回响应。
        
        Args:
            messages: 对话消息列表，格式同 chat 方法
            config: 配置字典，同 chat 方法
        
        Yields:
            流式响应块，每个块是一个字典，包含:
            - id: 响应 ID
            - choices: 回复选项列表，每个 choice 包含 delta（增量内容）
        
        Raises:
            OpenAIError: API 调用失败时抛出异常
        
        Example:
            ```python
            messages = [{"role": "user", "content": "讲个笑话"}]
            async for chunk in provider.stream(messages):
                print(chunk["choices"][0]["delta"]["content"], end="")
            ```
        """
        config = config or {}
        
        # 获取配置参数
        model = config.get("model") or get_default_model("openai")
        temperature = config.get("temperature", 0.7)
        
        logger.info(
            f"{Fore.BLUE}开始流式对话请求到 OpenAI，"
            f"模型: {model}, 消息数: {len(messages)}{Style.RESET_ALL}"
        )
        
        try:
            # 过滤参数
            filtered_config = {
                k: v for k, v in config.items()
                if k not in ["model", "temperature", "stream"]
            }
            
            # NOTE: 针对 429 限流错误进行指数退避重试
            wait_seconds = _INITIAL_WAIT_SECONDS
            for attempt in range(1, _MAX_RETRY_TIMES + 2):
                try:
                    # 发起流式请求
                    stream = await self.client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=temperature,
                        stream=True,  # 启用流式模式
                        **filtered_config
                    )
                    
                    # 逐块返回响应
                    async for chunk in stream:
                        yield chunk.model_dump()
                    
                    logger.info(
                        f"{Fore.GREEN}OpenAI 流式对话完成{Style.RESET_ALL}"
                    )
                    break
                    
                except httpx.HTTPStatusError as e:
                    # NOTE: 只对 429 限流错误进行重试，其他 HTTP 错误直接抛出
                    if e.response.status_code == 429 and attempt <= _MAX_RETRY_TIMES:
                        logger.warning(
                            f"{Fore.YELLOW}[OpenAI] 流式请求触发限流 (429 Too Many Requests)，"
                            f"第 {attempt}/{_MAX_RETRY_TIMES} 次重试，"
                            f"等待 {wait_seconds} 秒后继续...{Style.RESET_ALL}"
                        )
                        await asyncio.sleep(wait_seconds)
                        # 指数退避：等待时间翻倍
                        wait_seconds *= 2
                        continue
                    # 非 429 错误或已超出最大重试次数，向上抛出
                    logger.error(
                        f"{Fore.RED}OpenAI 流式请求失败 (HTTP {e.response.status_code}): {e}{Style.RESET_ALL}"
                    )
                    raise
                    
        except Exception as e:
            logger.error(
                f"{Fore.RED}OpenAI 流式请求失败: {e}{Style.RESET_ALL}"
            )
            raise
    
    async def embeddings(
        self,
        texts: List[str],
        model: str = None
    ) -> List[List[float]]:
        """
        文本向量化接口
        
        将输入的文本列表转换为向量表示，用于语义搜索、聚类等任务。
        
        Args:
            texts: 要向量化的文本列表
            model: 嵌入模型名称，默认为 "text-embedding-3-small"
                   可选值: text-embedding-3-small, text-embedding-3-large, text-embedding-ada-002
        
        Returns:
            嵌入向量列表，每个向量是一个 float 列表
        
        Raises:
            OpenAIError: API 调用失败时抛出异常
        
        Example:
            ```python
            texts = ["你好", "世界", "AI Agent"]
            vectors = await provider.embeddings(texts)
            # vectors[0] 是 "你好" 的向量表示
            ```
        """
        # 使用默认嵌入模型
        model = model or "text-embedding-3-small"
        
        logger.info(
            f"{Fore.BLUE}发送向量化请求到 OpenAI，"
            f"模型: {model}, 文本数: {len(texts)}{Style.RESET_ALL}"
        )
        
        try:
            # 调用 OpenAI 嵌入 API
            response = await self.client.embeddings.create(
                input=texts,
                model=model
            )
            
            # 提取嵌入向量
            embeddings = [data.embedding for data in response.data]
            
            logger.info(
                f"{Fore.GREEN}OpenAI 向量化成功，"
                f"返回向量数: {len(embeddings)}, "
                f"向量维度: {len(embeddings[0]) if embeddings else 0}{Style.RESET_ALL}"
            )
            
            return embeddings
            
        except Exception as e:
            logger.error(
                f"{Fore.RED}OpenAI 向量化请求失败: {e}{Style.RESET_ALL}"
            )
            raise


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
    
    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}OpenAI Provider 测试{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
    
    # 测试初始化
    provider = OpenAIProvider()
    print(f"创建 OpenAIProvider 实例: {type(provider).__name__}")
    
    # 测试配置信息
    print(f"\n{Fore.GREEN}测试完成!{Style.RESET_ALL}\n")
