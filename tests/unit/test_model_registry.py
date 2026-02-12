import pytest
from app.llm_hub.registry import ModelRegistry, ModelMetadata

class TestModelRegistry:
    
    @pytest.fixture
    def registry(self):
        return ModelRegistry()

    def test_initialization(self, registry):
        # 验证默认模型是否加载
        models = registry.list_models()
        assert len(models) > 0
        
        # 验证特定模型存在
        gpt4 = registry.get_model("gpt-4")
        assert gpt4 is not None
        assert gpt4.provider == "openai"
        
        claude = registry.get_model("claude-3-opus-20240229")
        assert claude is not None
        assert claude.provider == "anthropic"

    def test_register_model(self, registry):
        new_model = ModelMetadata(
            model_id="new-model",
            provider="test-provider",
            model_name="New Model",
            capabilities=["chat"],
            context_window=1000,
            max_output_tokens=100
        )
        registry.register_model(new_model)
        
        retrieved = registry.get_model("new-model")
        assert retrieved == new_model

    def test_list_models_by_provider(self, registry):
        openai_models = registry.list_models_by_provider("openai")
        assert len(openai_models) > 0
        for m in openai_models:
            assert m.provider == "openai"

        anthropic_models = registry.list_models_by_provider("anthropic")
        assert len(anthropic_models) > 0
        for m in anthropic_models:
            assert m.provider == "anthropic"
