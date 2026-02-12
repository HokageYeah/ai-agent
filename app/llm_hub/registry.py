from typing import Dict, List, Optional
from loguru import logger
from colorama import Fore, Style
from app.llm_hub.providers.base import ModelMetadata

class ModelRegistry:
    """
    模型注册中心
    管理所有可用模型及其元数据
    """
    def __init__(self):
        self._models: Dict[str, ModelMetadata] = {}
        self._initialize_default_models()

    def _initialize_default_models(self):
        """初始化默认模型"""
        defaults = [
            # OpenAI Models
            ModelMetadata(
                model_id="gpt-4",
                provider="openai",
                model_name="GPT-4",
                capabilities=["chat", "function_call"],
                context_window=8192,
                max_output_tokens=4096
            ),
            ModelMetadata(
                model_id="gpt-4-turbo",
                provider="openai",
                model_name="GPT-4 Turbo",
                capabilities=["chat", "function_call", "vision"],
                context_window=128000,
                max_output_tokens=4096
            ),
            ModelMetadata(
                model_id="gpt-3.5-turbo",
                provider="openai",
                model_name="GPT-3.5 Turbo",
                capabilities=["chat", "function_call"],
                context_window=16385,
                max_output_tokens=4096
            ),
            # Anthropic Models
            ModelMetadata(
                model_id="claude-3-opus-20240229",
                provider="anthropic",
                model_name="Claude 3 Opus",
                capabilities=["chat", "tool_use", "vision"],
                context_window=200000,
                max_output_tokens=4096
            ),
            ModelMetadata(
                model_id="claude-3-sonnet-20240229",
                provider="anthropic",
                model_name="Claude 3 Sonnet",
                capabilities=["chat", "tool_use", "vision"],
                context_window=200000,
                max_output_tokens=4096
            ),
             ModelMetadata(
                model_id="claude-3-haiku-20240307",
                provider="anthropic",
                model_name="Claude 3 Haiku",
                capabilities=["chat", "tool_use", "vision"],
                context_window=200000,
                max_output_tokens=4096
            )
        ]
        
        for model in defaults:
            self.register_model(model)
        
        logger.info(f"{Fore.CYAN}Initialized ModelRegistry with {len(self._models)} default models{Style.RESET_ALL}")

    def register_model(self, metadata: ModelMetadata):
        """注册模型"""
        self._models[metadata.model_id] = metadata
        logger.debug(f"Registered model: {metadata.model_id} ({metadata.provider})")

    def get_model(self, model_id: str) -> Optional[ModelMetadata]:
        """获取模型元数据"""
        return self._models.get(model_id)

    def list_models(self) -> List[ModelMetadata]:
        """列出所有模型"""
        return list(self._models.values())
    
    def list_models_by_provider(self, provider: str) -> List[ModelMetadata]:
        """按供应商列出模型"""
        return [m for m in self._models.values() if m.provider == provider]
