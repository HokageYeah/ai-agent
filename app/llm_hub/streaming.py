"""
流式输出管理器 (Streaming Manager)
==================================

本模块负责处理 LLM 的流式响应，提供统一的流式输出接口。

功能特点：
1. 统一不同供应商的流式响应格式
2. 支持流式数据的实时处理
3. 集成 Token 计数和内容过滤回调

作者: AI Agent Team
创建时间: 2026-02-12
"""

import asyncio
from typing import AsyncIterator, Dict, Any, Callable, Optional, List
from loguru import logger
from colorama import Fore, Style, Back


class StreamChunk:
    """
    流式输出块
    
    统一不同供应商的流式响应格式
    """
    
    def __init__(
        self,
        content: str = "",
        delta: str = "",
        is_end: bool = False,
        chunk_id: str = "",
        role: str = "assistant",
        usage: Optional[Dict[str, Any]] = None
    ):
        """
        初始化流式输出块
        
        Args:
            content: 已累积的内容
            delta: 本次新增的内容
            is_end: 是否是最后一个块
            chunk_id: 块的唯一标识
            role: 消息角色
            usage: Token 使用统计
        """
        self.content = content
        self.delta = delta
        self.is_end = is_end
        self.chunk_id = chunk_id
        self.role = role
        self.usage = usage
    
    def __repr__(self) -> str:
        """返回块的字符串表示"""
        return f"StreamChunk(content='{self.content[:50]}...', is_end={self.is_end})"


class StreamingManager:
    """
    流式输出管理器
    
    负责：
    1. 标准化不同供应商的流式响应格式
    2. 提供统一的流式输出接口
    3. 支持内容过滤和 Token 计数
    """
    
    def __init__(self):
        """
        初始化流式输出管理器
        """
        # 内容过滤器列表（在流式输出前调用）
        self._content_filters: List[Callable[[str], str]] = []
        
        # Token 计数器
        self._total_tokens = 0
        
        logger.info(f"{Fore.CYAN}初始化流式输出管理器 (StreamingManager){Style.RESET_ALL}")
    
    def add_content_filter(self, filter_func: Callable[[str], str]) -> None:
        """
        添加内容过滤器
        
        Args:
            filter_func: 过滤器函数，输入是原始内容，输出是过滤后的内容
        """
        self._content_filters.append(filter_func)
        logger.debug(f"{Fore.BLUE}添加内容过滤器，当前过滤器数量: {len(self._content_filters)}{Style.RESET_ALL}")
    
    def remove_content_filter(self, filter_func: Callable[[str], str]) -> None:
        """
        移除内容过滤器
        
        Args:
            filter_func: 要移除的过滤器函数
        """
        if filter_func in self._content_filters:
            self._content_filters.remove(filter_func)
            logger.debug(f"{Fore.BLUE}移除内容过滤器，当前过滤器数量: {len(self._content_filters)}{Style.RESET_ALL}")
    
    def clear_content_filters(self) -> None:
        """
        清空所有内容过滤器
        
        用于测试清理
        """
        self._content_filters.clear()
        logger.debug(f"{Fore.BLUE}已清空所有内容过滤器{Style.RESET_ALL}")
    
    def _apply_filters(self, content: str) -> str:
        """
        应用所有内容过滤器
        
        Args:
            content: 原始内容
            
        Returns:
            过滤后的内容
        """
        for filter_func in self._content_filters:
            content = filter_func(content)
        return content
    
    async def stream_response(
        self,
        provider_name: str,
        stream: AsyncIterator[Dict[str, Any]],
        config: Optional[Dict[str, Any]] = None
    ) -> AsyncIterator[StreamChunk]:
        """
        处理流式响应
        
        将不同供应商的流式响应转换为统一的 StreamChunk 格式
        
        Args:
            provider_name: 供应商名称 (openai, anthropic)
            stream: 原始流式响应
            config: 配置信息
            
        Yields:
            StreamChunk: 标准化后的流式输出块
        """
        config = config or {}
        accumulated_content = ""
        chunk_count = 0
        
        logger.info(f"{Fore.BLUE}开始处理 {provider_name} 流式响应{Style.RESET_ALL}")
        
        try:
            async for raw_chunk in stream:
                # 根据供应商类型解析响应
                chunk = self._parse_provider_chunk(provider_name, raw_chunk)
                
                if chunk is None:
                    # 跳过无法解析的块
                    continue
                
                # 累积内容
                accumulated_content += chunk.delta
                
                # 应用内容过滤器
                filtered_delta = self._apply_filters(chunk.delta)
                
                # 更新累积内容
                if filtered_delta != chunk.delta:
                    accumulated_content = accumulated_content[:-len(chunk.delta)] + filtered_delta
                    chunk.delta = filtered_delta
                    chunk.content = accumulated_content
                
                chunk_count += 1
                
                # 输出调试信息（每隔 10 个块打印一次）
                if chunk_count % 10 == 0:
                    logger.debug(
                        f"{Fore.BLUE}[{provider_name}] 流式输出块 #{chunk_count}: "
                        f"delta='{chunk.delta[:20]}...', "
                        f"accumulated={len(chunk.content)} chars{Style.RESET_ALL}"
                    )
                
                yield chunk
            
            # 输出最后一个块
            final_chunk = StreamChunk(
                content=accumulated_content,
                delta="",
                is_end=True,
                chunk_id=f"final-{chunk_count}",
                role="assistant"
            )
            
            logger.info(
                f"{Fore.GREEN}流式响应完成，共 {chunk_count} 个块，"
                f"总内容长度: {len(accumulated_content)} 字符{Style.RESET_ALL}"
            )
            
            yield final_chunk
            
        except asyncio.CancelledError:
            # 流式传输被取消
            logger.warning(f"{Fore.YELLOW}流式响应被取消{Style.RESET_ALL}")
            raise
        except Exception as e:
            logger.error(f"{Fore.RED}流式响应处理失败: {e}{Style.RESET_ALL}")
            raise
    
    def _parse_provider_chunk(
        self,
        provider_name: str,
        raw_chunk: Dict[str, Any]
    ) -> Optional[StreamChunk]:
        """
        解析不同供应商的原始流式块
        
        Args:
            provider_name: 供应商名称
            raw_chunk: 原始响应块
            
        Returns:
            标准化后的 StreamChunk，如果无法解析则返回 None
        """
        chunk_id = ""
        delta = ""
        content = ""
        is_end = False
        usage = None
        
        if provider_name == "openai":
            # OpenAI 格式解析
            # OpenAI 响应格式: {"id": "...", "object": "chat.completion.chunk", ...}
            choice = raw_chunk.get("choices", [{}])[0]
            delta_content = choice.get("delta", {}).get("content", "")
            finish_reason = choice.get("finish_reason", None)
            
            chunk_id = raw_chunk.get("id", "")
            delta = delta_content
            is_end = finish_reason is not None
            
            # 提取 usage（仅在最后一块）
            if is_end:
                usage = raw_chunk.get("usage", None)
                
        elif provider_name == "anthropic":
            # Anthropic 格式解析
            # Anthropic 响应格式: {"type": "message_start", ...} 或 {"type": "content_block_delta", ...}
            event_type = raw_chunk.get("type", "")
            
            if event_type == "message_start":
                # 消息开始块
                message = raw_chunk.get("message", {})
                chunk_id = message.get("id", "")
                is_end = False
                
            elif event_type == "content_block_delta":
                # 内容块增量
                delta_obj = raw_chunk.get("delta", {})
                delta = delta_obj.get("text", "")
                chunk_id = raw_chunk.get("id", "")
                is_end = False
                
            elif event_type == "message_delta":
                # 消息结束增量（包含 usage）
                usage = raw_chunk.get("usage", {})
                is_end = True
                
            elif event_type == "message_stop":
                # 消息结束
                is_end = True
                
            else:
                # 未知事件类型，跳过
                logger.debug(f"{Fore.YELLOW}未知 Anthropic 事件类型: {event_type}{Style.RESET_ALL}")
                return None
                
        else:
            # 未知供应商，使用通用格式
            logger.warning(f"{Fore.YELLOW}未知供应商: {provider_name}，使用通用格式解析{Style.RESET_ALL}")
            delta = str(raw_chunk)
        
        return StreamChunk(
            content=delta,  # 注意：这里只返回增量，累积由调用方处理
            delta=delta,
            is_end=is_end,
            chunk_id=chunk_id,
            usage=usage
        )
    
    def create_openai_compatible_stream(
        self,
        chunks: List[Dict[str, Any]]
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        创建 OpenAI 兼容的流式响应（用于测试）
        
        Args:
            chunks: 预定义的响应块列表
            
        Yields:
            模拟的 OpenAI 流式响应块
        """
        for i, chunk in enumerate(chunks):
            yield chunk
    
    def reset_token_count(self) -> None:
        """
        重置 Token 计数
        """
        self._total_tokens = 0
        logger.debug(f"{Fore.BLUE}Token 计数已重置{Style.RESET_ALL}")


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
    
    # 测试 StreamingManager
    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Streaming Manager 测试{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
    
    manager = create_streaming_manager()
    
    # 测试创建流式块
    chunk = StreamChunk(
        content="Hello",
        delta="Hello",
        is_end=False,
        chunk_id="test-1"
    )
    print(f"创建流式块: {chunk}")
    
    # 测试解析 OpenAI 格式
    openai_chunk = {
        "id": "test-id",
        "object": "chat.completion.chunk",
        "choices": [{
            "delta": {"content": " world"},
            "finish_reason": None
        }]
    }
    
    parsed = manager._parse_provider_chunk("openai", openai_chunk)
    print(f"解析 OpenAI 块: {parsed}")
    
    print(f"\n{Fore.GREEN}测试完成!{Style.RESET_ALL}\n")
