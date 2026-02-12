from abc import ABC, abstractmethod
from typing import AsyncIterator, List, Dict, Any, Union
import asyncio
import time

class LLMInterface(ABC):
    """LLM 统一接口定义"""
    
    @abstractmethod
    async def chat(
        self, 
        messages: List[Dict[str, str]],
        config: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        非流式对话接口
        
        Args:
            messages: 消息列表，格式如 [{"role": "user", "content": "..."}]
            config: 配置参数，如 model, temperature 等
            
        Returns:
            Dict: 包含响应内容和元数据的字典
        """
        pass
    
    @abstractmethod
    async def stream(
        self, 
        messages: List[Dict[str, str]],
        config: Dict[str, Any] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        流式对话接口
        
        Args:
            messages: 消息列表
            config: 配置参数
            
        Yields:
            Dict: 包含流式响应片段的字典
        """
        pass
    
    @abstractmethod
    async def embeddings(
        self,
        texts: List[str],
        model: str = None
    ) -> List[List[float]]:
        """
        文本向量化接口
        
        Args:
            texts: 文本列表
            model: 模型名称
            
        Returns:
            List[List[float]]: 向量列表
        """
        pass

class MockLLM(LLMInterface):
    """模拟 LLM 实现，用于测试"""
    
    def __init__(self, responses: Dict[str, str] = None, delay: float = 0.1):
        """
        初始化 MockLLM
        
        Args:
            responses: 预定义响应字典，key 为用户输入，value 为响应内容。若未匹配则返回默认响应。
            delay: 模拟延迟时间（秒）
        """
        self.responses = responses or {}
        self.delay = delay
        self.default_response = "这是 Mock LLM 的默认响应。"
        
    async def chat(
        self, 
        messages: List[Dict[str, str]],
        config: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """模拟非流式对话"""
        await asyncio.sleep(self.delay)
        
        last_message = messages[-1]["content"] if messages else ""
        response_text = self.responses.get(last_message, self.default_response)
        
        return {
            "content": response_text,
            "role": "assistant",
            "model": "mock-model",
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}
        }
    
    async def stream(
        self, 
        messages: List[Dict[str, str]],
        config: Dict[str, Any] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """模拟流式对话"""
        await asyncio.sleep(self.delay)
        
        last_message = messages[-1]["content"] if messages else ""
        response_text = self.responses.get(last_message, self.default_response)
        
        # 模拟分段输出
        chunk_size = 2
        for i in range(0, len(response_text), chunk_size):
            chunk = response_text[i:i+chunk_size]
            yield {
                "content": chunk,
                "role": "assistant",
                "model": "mock-model",
                "finish_reason": None
            }
            await asyncio.sleep(0.05)
            
        yield {
            "content": "",
            "role": "assistant",
            "model": "mock-model",
            "finish_reason": "stop"
        }

    async def embeddings(
        self,
        texts: List[str],
        model: str = None
    ) -> List[List[float]]:
        """模拟向量化"""
        await asyncio.sleep(self.delay)
        # 返回固定维度的随机向量（模拟）
        return [[0.1] * 1536 for _ in texts]

class LLMFactory:
    """LLM 工厂类"""
    
    @staticmethod
    def create_llm(provider: str, **kwargs) -> LLMInterface:
        """
        创建 LLM 实例
        
        Args:
            provider: 供应商名称 ("mock", "openai", "anthropic")
            **kwargs: 初始化参数
            
        Returns:
            LLMInterface: LLM 实例
        """
        if provider == "mock":
            return MockLLM(**kwargs)
        else:
            raise ValueError(f"Unsupported provider: {provider}")
