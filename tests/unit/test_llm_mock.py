import pytest
from app.core.llm_mock import LLMFactory, MockLLM

@pytest.mark.asyncio
async def test_mock_llm_chat():
    """测试 Mock LLM 的非流式对话"""
    responses = {"你好": "你好！我是 Mock AI。"}
    llm = LLMFactory.create_llm("mock", responses=responses)
    
    messages = [{"role": "user", "content": "你好"}]
    response = await llm.chat(messages)
    
    assert response["content"] == "你好！我是 Mock AI。"
    assert response["role"] == "assistant"

@pytest.mark.asyncio
async def test_mock_llm_default_response():
    """测试 Mock LLM 的默认响应"""
    llm = LLMFactory.create_llm("mock")
    
    messages = [{"role": "user", "content": "未知问题"}]
    response = await llm.chat(messages)
    
    assert response["content"] == "这是 Mock LLM 的默认响应。"

@pytest.mark.asyncio
async def test_mock_llm_stream():
    """测试 Mock LLM 的流式对话"""
    responses = {"Hello": "Hi there"}
    llm = LLMFactory.create_llm("mock", responses=responses)
    
    messages = [{"role": "user", "content": "Hello"}]
    chunks = []
    async for chunk in llm.stream(messages):
        chunks.append(chunk["content"])
        
    full_response = "".join(chunks)
    assert full_response == "Hi there"

@pytest.mark.asyncio
async def test_mock_llm_embeddings():
    """测试 Mock LLM 的向量化"""
    llm = LLMFactory.create_llm("mock")
    texts = ["hello", "world"]
    embeddings = await llm.embeddings(texts)
    
    assert len(embeddings) == 2
    assert len(embeddings[0]) == 1536

def test_llm_factory_invalid_provider():
    """测试工厂类处理无效供应商"""
    with pytest.raises(ValueError):
        LLMFactory.create_llm("unknown")
