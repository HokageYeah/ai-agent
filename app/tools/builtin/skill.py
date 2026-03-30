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
    """
    将外部技能包安装到项目工作区。

    planning_safe = False：
        安装操作会在磁盘落地文件（SKILL.md 目录），属于不可逆副作用。
        必须在 Execution Node 内执行，以便 Reflection 引擎能观察到安装结果，
        避免 Planning 阶段完成安装后 Reflection 误判"未安装"而触发无效重规划。
    """

    # 有副作用——磁盘写入，禁止在 Planning tool-calling loop 中调用
    planning_safe: bool = False

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

    @staticmethod
    def _pick_first_non_empty(
        params: Dict[str, Any],
        candidate_keys: list[str],
    ) -> tuple[str, Optional[str]]:
        """
        从一组候选字段中选出第一个非空值。

        设计原因：
        - direct tool call 会跳过严格 schema 校验；
        - LLM 在安装类任务中经常把 `package` 漂移写成 `reference`、`skill_id`
          或 `package_ref`；
        - 因此兼容逻辑应沉淀在工具层，而不是散落在各个调用点。
        """
        for key in candidate_keys:
            value = params.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text, key
        return "", None

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        """把 LLM 常见的布尔漂移值统一归一化为 bool。"""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value or "").strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off", ""}:
            return False
        return bool(value)

    def _normalize_install_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        归一化技能安装参数，兼容规划阶段常见的字段别名漂移。

        线上已观测到的真实案例：
        - `package` 被写成 `reference`
        - `package` 被写成 `source`
        - `skill_name` 被写成 `skill_id`
        """
        raw_params = dict(params or {})

        package, package_source = self._pick_first_non_empty(
            raw_params,
            [
                "package",
                "reference",
                "source",
                "package_ref",
                "package_source",
                "install_ref",
                "skill_reference",
                "install_source",
                "ref",
                "uri",
                "url",
                "repo",
                "command",
            ],
        )
        skill_name, skill_name_source = self._pick_first_non_empty(
            raw_params,
            [
                "skill_name",
                "target_skill",
                "skill_id",
                "name",
                "slug",
            ],
        )

        # 若 LLM 只给了 skill_id / slug，没有给 package，也允许继续走安装服务。
        if not package:
            package, package_source = self._pick_first_non_empty(
                raw_params,
                ["skill_id", "skill_name", "name", "slug"],
            )

        overwrite_source = "overwrite"
        overwrite_value: Any = raw_params.get("overwrite")
        if overwrite_value is None:
            for alias in ("force", "replace"):
                if alias in raw_params:
                    overwrite_value = raw_params.get(alias)
                    overwrite_source = alias
                    break

        alias_notes = []
        if package_source and package_source != "package":
            alias_notes.append(f"package<-{package_source}")
        if skill_name_source and skill_name_source != "skill_name":
            alias_notes.append(f"skill_name<-{skill_name_source}")
        if overwrite_source != "overwrite":
            alias_notes.append(f"overwrite<-{overwrite_source}")

        return {
            "package": package,
            "skill_name": skill_name or None,
            "overwrite": self._coerce_bool(overwrite_value),
            "alias_notes": alias_notes,
        }

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self._normalize_install_params(params)
        package = normalized["package"]
        skill_name = normalized["skill_name"]
        overwrite = normalized["overwrite"]

        if normalized["alias_notes"]:
            logger.info(
                f"{Fore.CYAN}[SkillInstallTool] 检测到安装参数别名漂移，已自动归一化 | "
                f"aliases={normalized['alias_notes']} | raw_keys={sorted((params or {}).keys())}"
                f"{Style.RESET_ALL}"
            )

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
