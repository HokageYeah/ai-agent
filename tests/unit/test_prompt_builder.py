import pytest
from app.llm_hub.prompt_builder import PromptBuilder

class TestPromptBuilder:
    
    @pytest.fixture
    def builder(self):
        return PromptBuilder()

    def test_basic_build(self, builder):
        messages = [{"role": "user", "content": "Hello"}]
        result = builder.build(messages)
        assert len(result) == 1
        assert result[0]["content"] == "Hello"

    def test_system_prompt_insertion(self, builder):
        messages = [{"role": "user", "content": "Hello"}]
        system_prompt = "You are a helpful assistant."
        
        result = builder.build(messages, system_prompt=system_prompt)
        
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[0]["content"] == system_prompt
        assert result[1]["role"] == "user"

    def test_system_prompt_merge(self, builder):
        messages = [
            {"role": "system", "content": "Original system prompt."},
            {"role": "user", "content": "Hello"}
        ]
        system_prompt = "Additional system prompt."
        
        result = builder.build(messages, system_prompt=system_prompt)
        
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert "Original system prompt." in result[0]["content"]
        assert "Additional system prompt." in result[0]["content"]

    def test_context_insertion(self, builder):
        messages = [{"role": "user", "content": "Question"}]
        context = [{"text": "Context 1"}, {"text": "Context 2"}]
        
        result = builder.build(messages, context=context)
        
        assert len(result) >= 1
        # 验证上下文是否被插入到某条消息中
        found_context = False
        for msg in result:
            if "Context 1" in msg["content"]:
                found_context = True
                break
        assert found_context
