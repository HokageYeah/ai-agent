"""
技能安装工具模块
================

本工具把“安装外部技能包”沉淀为一等内置工具，避免 LLM 继续用 `shell_exec`
盲目执行 `npx skills ...` 命令。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from colorama import Fore, Style
from loguru import logger

from app.skills.installer import SkillInstallerService
from app.tools.base import Tool, ToolSchema


class SkillInstallTool(Tool):
    """将外部技能包安装到项目工作区。"""

    def __init__(
        self,
        installer: Optional[SkillInstallerService] = None,
        timeout_seconds: int = 300,
    ):
        self._name = "skill_install"
        self._description = (
            "将 Skills CLI 技能包安装到当前项目的技能工作区。"
            "支持完整安装命令、owner/repo@skill、URL 或历史的 `npx skills install ...` 写法。"
        )
        self._installer = installer or SkillInstallerService(timeout_seconds=timeout_seconds)
        logger.info(
            f"{Fore.CYAN}[SkillInstallTool] 初始化完成 | timeout={timeout_seconds}s{Style.RESET_ALL}"
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {
                    "package": {
                        "type": "string",
                        "description": (
                            "技能安装来源。推荐传完整技能引用 "
                            "（如 `owner/repo@skill`），也支持完整命令 "
                            "（如 `npx skills add owner/repo@skill`）或历史 `install` 写法。"
                        ),
                    },
                    "skill_name": {
                        "type": "string",
                        "description": "可选的技能名，用于 URL / 多技能仓库场景精确定位。",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "若工作区已存在同名技能目录，是否覆盖写入。",
                        "default": False,
                    },
                },
                "required": ["package"],
                "additionalProperties": False,
            },
        )

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        package = str(params.get("package") or "").strip()
        skill_name = str(params.get("skill_name") or "").strip() or None
        overwrite = bool(params.get("overwrite", False))

        if not package:
            logger.warning(
                f"{Fore.YELLOW}[SkillInstallTool] package 为空，拒绝执行{Style.RESET_ALL}"
            )
            return {"success": False, "error": "package 不能为空"}

        logger.info(
            f"{Fore.CYAN}[SkillInstallTool] 开始执行技能安装 | "
            f"package={package} | skill_name={skill_name or '自动识别'} | "
            f"overwrite={overwrite}{Style.RESET_ALL}"
        )
        return await self._installer.install(
            package=package,
            skill_name=skill_name,
            overwrite=overwrite,
        )
