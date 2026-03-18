from typing import Dict, List, Optional
from loguru import logger
from colorama import Fore, Style

from app.core.config import get_default_model, infer_provider_from_model
from app.llm_hub.providers.base import ModelMetadata


class ModelRegistry:
    """
    模型注册中心
    管理所有可用模型及其元数据
    """

    def __init__(self):
        self._models: Dict[str, ModelMetadata] = {}
        self._initialize_default_models()

    def _build_model_metadata(self, model_id: str) -> ModelMetadata:
        """根据模型 ID 构建默认元数据。"""
        known_models = {
            "gpt-5.3-codex": ModelMetadata(
                model_id="gpt-5.3-codex",
                provider="openai",
                model_name="GPT-5.3 Codex",
                capabilities=["chat", "function_call", "reasoning"],
                context_window=128000,
                max_output_tokens=4096,
            ),
            "gpt-4": ModelMetadata(
                model_id="gpt-4",
                provider="openai",
                model_name="GPT-4",
                capabilities=["chat", "function_call"],
                context_window=8192,
                max_output_tokens=4096,
            ),
            "gpt-4-turbo": ModelMetadata(
                model_id="gpt-4-turbo",
                provider="openai",
                model_name="GPT-4 Turbo",
                capabilities=["chat", "function_call", "vision"],
                context_window=128000,
                max_output_tokens=4096,
            ),
            "gpt-3.5-turbo": ModelMetadata(
                model_id="gpt-3.5-turbo",
                provider="openai",
                model_name="GPT-3.5 Turbo",
                capabilities=["chat", "function_call"],
                context_window=16385,
                max_output_tokens=4096,
            ),
            "claude-3-opus-20240229": ModelMetadata(
                model_id="claude-3-opus-20240229",
                provider="anthropic",
                model_name="Claude 3 Opus",
                capabilities=["chat", "tool_use", "vision"],
                context_window=200000,
                max_output_tokens=4096,
            ),
            "claude-3-sonnet-20240229": ModelMetadata(
                model_id="claude-3-sonnet-20240229",
                provider="anthropic",
                model_name="Claude 3 Sonnet",
                capabilities=["chat", "tool_use", "vision"],
                context_window=200000,
                max_output_tokens=4096,
            ),
            "claude-3-haiku-20240307": ModelMetadata(
                model_id="claude-3-haiku-20240307",
                provider="anthropic",
                model_name="Claude 3 Haiku",
                capabilities=["chat", "tool_use", "vision"],
                context_window=200000,
                max_output_tokens=4096,
            ),
        }

        metadata = known_models.get(model_id)
        if metadata is not None:
            return metadata

        provider = infer_provider_from_model(model_id)
        capabilities = ["chat", "tool_use", "vision"] if provider == "anthropic" else ["chat", "function_call"]
        context_window = 200000 if provider == "anthropic" else 128000

        return ModelMetadata(
            model_id=model_id,
            provider=provider,
            model_name=model_id,
            capabilities=capabilities,
            context_window=context_window,
            max_output_tokens=4096,
        )

    def _initialize_default_models(self):
        """初始化默认模型。"""
        default_model_ids = [
            get_default_model("openai"),
            "gpt-5.3-codex",
            "gpt-4",
            "gpt-4-turbo",
            "gpt-3.5-turbo",
            get_default_model("anthropic"),
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
        ]

        for model_id in dict.fromkeys(default_model_ids):
            self.register_model(self._build_model_metadata(model_id))

        logger.info(
            f"{Fore.CYAN}模型注册中心初始化完成，共 {len(self._models)} 个默认模型 | "
            f"OpenAI 默认={get_default_model('openai')} | "
            f"Anthropic 默认={get_default_model('anthropic')}{Style.RESET_ALL}"
        )

    def register_model(self, metadata: ModelMetadata):
        """注册模型"""
        self._models[metadata.model_id] = metadata
        logger.debug(f"已注册模型: {metadata.model_id} ({metadata.provider})")

    def get_model(self, model_id: str) -> Optional[ModelMetadata]:
        """获取模型元数据"""
        return self._models.get(model_id)

    def list_models(self) -> List[ModelMetadata]:
        """列出所有模型"""
        return list(self._models.values())

    def list_models_by_provider(self, provider: str) -> List[ModelMetadata]:
        """按供应商列出模型"""
        return [m for m in self._models.values() if m.provider == provider]
