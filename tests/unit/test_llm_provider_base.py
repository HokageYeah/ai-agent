import pytest
from app.llm_hub.providers.base import LLMProvider, ModelMetadata
from app.core.llm_mock import MockLLM

class ConcreteProvider(LLMProvider):
    """具体实现的 Provider，用于测试抽象基类"""
    
    async def chat(self, messages, config=None):
        return {"role": "assistant", "content": "mock response"}
        
    async def stream(self, messages, config=None):
        yield {"content": "mock"}
        
    async def embeddings(self, texts, model=None):
        return [[0.1]]

def test_model_metadata_creation():
    """测试模型元数据创建"""
    metadata = ModelMetadata(
        model_id="gpt-4",
        provider="openai",
        model_name="GPT-4",
        capabilities=["chat", "code"],
        context_window=8192,
        max_output_tokens=4096
    )
    
    assert metadata.model_id == "gpt-4"
    assert metadata.provider == "openai"
    assert metadata.is_available is True

@pytest.mark.asyncio
async def test_llm_provider_inheritance():
    """测试 Provider 继承和实例化"""
    # 验证无法实例化抽象类
    with pytest.raises(TypeError):
        LLMProvider()
        
    # 验证具体实现类
    provider = ConcreteProvider()
    response = await provider.chat([{"role": "user", "content": "hi"}])
    assert response["role"] == "assistant"
