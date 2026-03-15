"""
提示词管理工具。

职责：
1. 从文件系统加载 Prompt 模板并进行缓存。
2. 使用 Jinja2 渲染模板。
3. 提供统一的提示词目录解析与访问能力。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from jinja2 import Environment, StrictUndefined, TemplateError
from loguru import logger

from app.utils.resource_path import get_resource_path


DEFAULT_PROMPT_DIR = "app/prompt"


class PromptTemplate:
    """提示词模板对象，负责单模板渲染。"""

    def __init__(self, name: str, source: str, env: Environment):
        self.name = name
        self.source = source
        self._env = env
        self._template = env.from_string(source)

    def render(self, **kwargs: Any) -> str:
        """渲染模板。"""
        try:
            return self._template.render(**kwargs).strip()
        except TemplateError as exc:
            logger.error(f"提示词模板渲染失败 [{self.name}]: {exc}")
            raise ValueError(f"提示词模板渲染失败 [{self.name}]: {exc}") from exc


class PromptManager:
    """
    提示词管理器。

    - 支持按文件名加载 `.txt` 模板
    - 支持缓存避免重复 IO
    - 支持严格变量校验（缺失变量直接抛错）
    """

    def __init__(self, prompt_dir: Optional[str] = None):
        raw_dir = prompt_dir or DEFAULT_PROMPT_DIR
        resolved_dir = get_resource_path(raw_dir)

        self.prompt_dir = Path(resolved_dir)
        self._cache: Dict[str, PromptTemplate] = {}
        self._env = Environment(
            autoescape=False,
            trim_blocks=False,
            lstrip_blocks=False,
            keep_trailing_newline=True,
            undefined=StrictUndefined,
        )

        if self.prompt_dir.exists():
            logger.info(f"提示词管理器初始化完成，目录: {self.prompt_dir}")
        else:
            logger.warning(f"提示词目录不存在: {self.prompt_dir}")

    def _normalize_file_name(self, name: str) -> str:
        return name if name.endswith('.txt') else f"{name}.txt"

    def load_prompt(self, name: str, file_name: Optional[str] = None) -> PromptTemplate:
        """加载模板到缓存并返回。"""
        cache_key = name
        if cache_key in self._cache:
            return self._cache[cache_key]

        resolved_file = self._normalize_file_name(file_name or name)
        file_path = self.prompt_dir / resolved_file
        if not file_path.exists():
            raise FileNotFoundError(f"提示词文件不存在: {file_path}")

        source = file_path.read_text(encoding='utf-8')
        template = PromptTemplate(cache_key, source, self._env)
        self._cache[cache_key] = template
        logger.debug(f"提示词加载成功: {cache_key} -> {resolved_file}")
        return template

    def get_prompt(self, name: str) -> PromptTemplate:
        """获取提示词模板。"""
        if name not in self._cache:
            self.load_prompt(name)
        return self._cache[name]

    def render_prompt(self, name: str, **kwargs: Any) -> str:
        """渲染指定名称的提示词模板。"""
        return self.get_prompt(name).render(**kwargs)

    def add_prompt(self, name: str, content: str) -> None:
        """添加动态模板到缓存（不落盘）。"""
        self._cache[name] = PromptTemplate(name, content, self._env)

    def reload_prompt(self, name: str, file_name: Optional[str] = None) -> PromptTemplate:
        """强制重载模板。"""
        self._cache.pop(name, None)
        return self.load_prompt(name=name, file_name=file_name)

    def clear_cache(self) -> None:
        """清空缓存。"""
        self._cache.clear()

    def list_prompts(self) -> list[str]:
        """返回已缓存模板名。"""
        return list(self._cache.keys())

    def list_prompt_files(self) -> list[str]:
        """列出提示词目录中的 txt 文件。"""
        if not self.prompt_dir.exists():
            return []
        return sorted([item.name for item in self.prompt_dir.glob('*.txt')])


_global_prompt_manager: Optional[PromptManager] = None


def get_prompt_manager(prompt_dir: Optional[str] = None) -> PromptManager:
    """获取全局提示词管理器（单例）。"""
    global _global_prompt_manager
    if _global_prompt_manager is None:
        _global_prompt_manager = PromptManager(prompt_dir=prompt_dir)
    return _global_prompt_manager


def load_and_render_prompt(name: str, prompt_dir: Optional[str] = None, **kwargs: Any) -> str:
    """便捷函数：加载并渲染提示词。"""
    manager = get_prompt_manager(prompt_dir=prompt_dir)
    return manager.render_prompt(name, **kwargs)
