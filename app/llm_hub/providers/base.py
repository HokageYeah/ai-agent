from abc import ABC, abstractmethod
from typing import AsyncIterator, List, Dict, Any, Optional
from pydantic import BaseModel
from app.core.llm_mock import LLMInterface

class ModelMetadata(BaseModel):
    """模型元数据"""
    model_id: str                    # 模型唯一标识
    provider: str                    # 供应商 (openai, anthropic, etc.)
    model_name: str                  # 模型展示名称
    capabilities: List[str]          # 能力标签 (chat, embedding, vision, etc.)
    context_window: int              # 上下文窗口大小
    max_output_tokens: int          # 最大输出 tokens
    is_available: bool = True       # 是否可用

class LLMProvider(LLMInterface, ABC):
    """
    LLM 供应商抽象基类
    继承自 core.LLMInterface 以保持接口一致性
    """
    
    @abstractmethod
    async def chat(
        self, 
        messages: List[Dict[str, str]],
        config: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """非流式对话"""
        pass
    
    @abstractmethod
    async def stream(
        self, 
        messages: List[Dict[str, str]],
        config: Dict[str, Any] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """流式对话"""
        pass
    
    @abstractmethod
    async def embeddings(
        self,
        texts: List[str],
        model: str = None
    ) -> List[List[float]]:
        """文本向量化"""
        pass
