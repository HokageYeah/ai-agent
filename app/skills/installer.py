"""
技能安装服务模块
================

本模块负责将外部 Skills CLI 技能包稳定安装到项目工作区。

设计目标：
1. 不再让 LLM 直接拼接 `shell_exec` 安装命令，减少命令猜错导致的失败。
2. 统一把技能落地到项目配置的 Agent 工作区（默认 `app/skills/skills_md`）。
3. 兼容历史遗留输入，例如 `npx skills install xxx`，在服务层自动规范化为 `npx skills add ...`。
4. 安装过程使用临时 `CODEX_HOME` 隔离目录，成功后再复制到项目工作区，避免污染用户本机全局目录。
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from colorama import Fore, Style
from loguru import logger

from app.core.config import get_agent_workspace_dir, resolve_agent_workspace_dir

SKILL_FILE_NAME = "SKILL.md"
INSTALL_REF_PATTERN = re.compile(
    r"([A-Za-z0-9._-]+/[A-Za-z0-9._-]+@[A-Za-z0-9._-]+)"
)
FRONTMATTER_NAME_PATTERN = re.compile(
    r"(?m)^name:\s*([A-Za-z0-9._-]+)\s*$"
)


@dataclass
class ParsedSkillInstallRequest:
    """结构化的技能安装请求。"""

    original_input: str
    package_ref: str
    skill_name: Optional[str] = None
    passthrough_args: List[str] = field(default_factory=list)
    used_legacy_install_alias: bool = False


class SkillInstallerService:
    """
    技能安装服务。

    说明：
    - 安装命令实际通过 `npx skills add ...` 执行；
    - 技能先安装到临时 `CODEX_HOME/skills`，再复制进项目工作区；
    - 这样既能兼容 Skills CLI 的默认目录约定，也能保证本项目只扫描自己的技能目录。
    """

    def __init__(
        self,
        workspace_dir: Optional[str | Path] = None,
        timeout_seconds: int = 180,
    ):
        self.workspace_dir = (
            resolve_agent_workspace_dir(str(workspace_dir))
            if workspace_dir
            else get_agent_workspace_dir()
        )
        self.timeout_seconds = timeout_seconds
        logger.info(
            f"{Fore.CYAN}[SkillInstallerService] 初始化完成 | "
            f"workspace={self.workspace_dir} | timeout={self.timeout_seconds}s{Style.RESET_ALL}"
        )

    async def install(
        self,
        package: str,
        skill_name: Optional[str] = None,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """
        安装技能到项目工作区。

        Args:
            package: 技能引用，支持：
                1. 完整命令：`npx skills add owner/repo@skill`
                2. 技能引用：`owner/repo@skill`
                3. 历史写法：`npx skills install xxx`
                4. 简短 slug：`wechat-article-search`（会先尝试 find 解析）
            skill_name: 可选的目标技能名（主要给 URL / 多技能仓库场景使用）
            overwrite: 目标已存在时是否覆盖
        """
        try:
            parsed = self._normalize_request(package=package, skill_name=skill_name)
        except ValueError as exc:
            logger.warning(
                f"{Fore.YELLOW}[SkillInstallerService] 安装请求无效: {exc}{Style.RESET_ALL}"
            )
            return {
                "success": False,
                "error": str(exc),
                "workspace_dir": str(self.workspace_dir),
                "package": package,
            }

        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            f"{Fore.CYAN}[SkillInstallerService] 开始安装技能 | input='{parsed.original_input}' | "
            f"package_ref={parsed.package_ref} | skill_name={parsed.skill_name or '自动识别'} | "
            f"overwrite={overwrite}{Style.RESET_ALL}"
        )

        with tempfile.TemporaryDirectory(prefix="ai-agent-skill-home-") as temp_home:
            codex_home = Path(temp_home).resolve()
            exec_env = {**os.environ, "CODEX_HOME": str(codex_home)}
            requested_package_ref = parsed.package_ref
            effective_parsed = parsed
            recovery_context: Optional[Dict[str, Any]] = None

            if self._looks_like_plain_skill_slug(parsed.package_ref):
                logger.info(
                    f"{Fore.CYAN}[SkillInstallerService] 检测到简短技能标识，先尝试通过 find 解析完整引用: "
                    f"{parsed.package_ref}{Style.RESET_ALL}"
                )
                inferred_ref = await self._resolve_package_ref_from_find(
                    query=parsed.package_ref,
                    env=exec_env,
                    cwd=str(codex_home),
                )
                if inferred_ref:
                    parsed.package_ref = inferred_ref
                    logger.info(
                        f"{Fore.GREEN}[SkillInstallerService] 已解析到完整技能引用: "
                        f"{parsed.package_ref}{Style.RESET_ALL}"
                    )
                else:
                    logger.warning(
                        f"{Fore.YELLOW}[SkillInstallerService] 未从 find 结果解析到完整引用，"
                        f"将继续尝试原始引用安装: {parsed.package_ref}{Style.RESET_ALL}"
                    )

            effective_parsed = parsed
            install_command = self._build_install_command(effective_parsed)
            cli_result = await self._run_command(
                command=install_command,
                env=exec_env,
                cwd=str(codex_home),
                timeout_seconds=self.timeout_seconds,
            )
            if cli_result["return_code"] != 0:
                recovery_context = await self._attempt_recover_from_failed_install(
                    parsed=effective_parsed,
                    cli_result=cli_result,
                    env=exec_env,
                    cwd=str(codex_home),
                )
                retry_package_ref = (recovery_context or {}).get("retry_package_ref")
                if retry_package_ref:
                    effective_parsed = ParsedSkillInstallRequest(
                        original_input=effective_parsed.original_input,
                        package_ref=retry_package_ref,
                        skill_name=effective_parsed.skill_name,
                        passthrough_args=list(effective_parsed.passthrough_args),
                        used_legacy_install_alias=effective_parsed.used_legacy_install_alias,
                    )
                    retry_command = self._build_install_command(effective_parsed)
                    logger.warning(
                        f"{Fore.YELLOW}[SkillInstallerService] 首次安装失败，准备基于真实 find 结果回退重试 | "
                        f"retry_package_ref={retry_package_ref}{Style.RESET_ALL}"
                    )
                    cli_result = await self._run_command(
                        command=retry_command,
                        env=exec_env,
                        cwd=str(codex_home),
                        timeout_seconds=self.timeout_seconds,
                    )

            if cli_result["return_code"] != 0:
                error_message = self._format_cli_failure(
                    parsed=effective_parsed,
                    cli_result=cli_result,
                    recovery_context=recovery_context,
                )
                logger.error(
                    f"{Fore.RED}[SkillInstallerService] Skills CLI 安装失败: {error_message}{Style.RESET_ALL}"
                )
                return {
                    "success": False,
                    "error": error_message,
                    "package": package,
                    "original_package_ref": requested_package_ref,
                    "resolved_package_ref": effective_parsed.package_ref,
                    "cli_command": cli_result["command"],
                    "stdout": cli_result["stdout"],
                    "stderr": cli_result["stderr"],
                    "workspace_dir": str(self.workspace_dir),
                    "used_legacy_install_alias": effective_parsed.used_legacy_install_alias,
                    **self._build_recovery_fields(recovery_context),
                }

            skill_root = codex_home / "skills"
            installed_skill_dir = self._locate_installed_skill_dir(
                skill_root=skill_root,
                preferred_skill_name=effective_parsed.skill_name,
                preferred_package_ref=effective_parsed.package_ref,
            )
            if installed_skill_dir is None:
                error_message = (
                    f"Skills CLI 命令执行成功，但未在临时目录 {skill_root} 中找到包含 {SKILL_FILE_NAME} 的技能包"
                )
                logger.error(
                    f"{Fore.RED}[SkillInstallerService] {error_message}{Style.RESET_ALL}"
                )
                return {
                    "success": False,
                    "error": error_message,
                    "package": package,
                    "original_package_ref": requested_package_ref,
                    "resolved_package_ref": effective_parsed.package_ref,
                    "cli_command": cli_result["command"],
                    "stdout": cli_result["stdout"],
                    "stderr": cli_result["stderr"],
                    "workspace_dir": str(self.workspace_dir),
                    "used_legacy_install_alias": effective_parsed.used_legacy_install_alias,
                    **self._build_recovery_fields(recovery_context),
                }

            final_skill_name = self._infer_final_skill_name(
                installed_skill_dir=installed_skill_dir,
                preferred_skill_name=effective_parsed.skill_name,
            )
            target_dir = self.workspace_dir / final_skill_name
            target_skill_file = target_dir / SKILL_FILE_NAME

            if target_dir.exists():
                if overwrite:
                    logger.warning(
                        f"{Fore.YELLOW}[SkillInstallerService] 目标技能目录已存在，准备覆盖: {target_dir}{Style.RESET_ALL}"
                    )
                    shutil.rmtree(target_dir)
                else:
                    logger.info(
                        f"{Fore.GREEN}[SkillInstallerService] 技能已存在，跳过覆盖: {target_dir}{Style.RESET_ALL}"
                    )
                    return {
                        "success": True,
                        "skipped": True,
                        "overwritten": False,
                        "package": package,
                        "original_package_ref": requested_package_ref,
                        "resolved_package_ref": effective_parsed.package_ref,
                        "skill_name": final_skill_name,
                        "installed_path": str(target_dir),
                        "skill_file": str(target_skill_file),
                        "workspace_dir": str(self.workspace_dir),
                        "cli_command": cli_result["command"],
                        "stdout": cli_result["stdout"],
                        "stderr": cli_result["stderr"],
                        "used_legacy_install_alias": effective_parsed.used_legacy_install_alias,
                        **self._build_recovery_fields(recovery_context),
                        "message": "技能已存在，未执行覆盖写入",
                    }

            shutil.copytree(installed_skill_dir, target_dir)
            if not target_skill_file.exists():
                error_message = f"技能目录复制完成，但未找到目标文件: {target_skill_file}"
                logger.error(
                    f"{Fore.RED}[SkillInstallerService] {error_message}{Style.RESET_ALL}"
                )
                return {
                    "success": False,
                    "error": error_message,
                    "package": package,
                    "original_package_ref": requested_package_ref,
                    "resolved_package_ref": effective_parsed.package_ref,
                    "skill_name": final_skill_name,
                    "installed_path": str(target_dir),
                    "workspace_dir": str(self.workspace_dir),
                    "cli_command": cli_result["command"],
                    "stdout": cli_result["stdout"],
                    "stderr": cli_result["stderr"],
                    "used_legacy_install_alias": effective_parsed.used_legacy_install_alias,
                    **self._build_recovery_fields(recovery_context),
                }

            logger.info(
                f"{Fore.GREEN}[SkillInstallerService] 技能安装成功 | skill={final_skill_name} | "
                f"path={target_dir}{Style.RESET_ALL}"
            )
            return {
                "success": True,
                "skipped": False,
                "overwritten": overwrite,
                "package": package,
                "original_package_ref": requested_package_ref,
                "resolved_package_ref": effective_parsed.package_ref,
                "skill_name": final_skill_name,
                "installed_path": str(target_dir),
                "skill_file": str(target_skill_file),
                "workspace_dir": str(self.workspace_dir),
                "cli_command": cli_result["command"],
                "stdout": cli_result["stdout"],
                "stderr": cli_result["stderr"],
                "used_legacy_install_alias": effective_parsed.used_legacy_install_alias,
                **self._build_recovery_fields(recovery_context),
                "message": "技能已安装到项目工作区",
            }

    def _normalize_request(
        self,
        package: str,
        skill_name: Optional[str] = None,
    ) -> ParsedSkillInstallRequest:
        """
        规范化技能安装请求。

        这里兼容两类输入：
        1. 用户 / 历史上下文直接给了 CLI 命令
        2. 用户只给了技能包引用
        """
        raw_input = str(package or "").strip()
        normalized_skill_name = (skill_name or "").strip() or None
        if not raw_input:
            raise ValueError("package 不能为空，至少要提供技能引用或完整安装命令")

        if raw_input.startswith("npx ") or raw_input.startswith("skills "):
            try:
                tokens = shlex.split(raw_input)
            except ValueError as exc:
                raise ValueError(f"无法解析技能安装命令: {exc}") from exc

            if tokens and tokens[0] == "npx":
                tokens = tokens[1:]
            if len(tokens) < 3 or tokens[0] != "skills":
                raise ValueError("仅支持 `npx skills add ...` 或 `npx skills install ...` 格式")

            action = tokens[1].strip().lower()
            if action not in {"add", "install"}:
                raise ValueError("仅支持 `skills add` / `skills install` 安装命令")

            passthrough_args: List[str] = []
            parsed_package_ref: Optional[str] = None
            index = 2
            while index < len(tokens):
                token = tokens[index]
                if token in {"-g", "--global", "-y", "--yes"}:
                    passthrough_args.append(token)
                    index += 1
                    continue
                if token == "--skill":
                    if index + 1 >= len(tokens):
                        raise ValueError("命令中的 --skill 缺少技能名")
                    normalized_skill_name = normalized_skill_name or tokens[index + 1].strip()
                    passthrough_args.extend([token, tokens[index + 1]])
                    index += 2
                    continue
                if token.startswith("--skill="):
                    value = token.split("=", 1)[1].strip()
                    normalized_skill_name = normalized_skill_name or value or None
                    passthrough_args.append(token)
                    index += 1
                    continue
                if parsed_package_ref is None:
                    parsed_package_ref = token.strip()
                else:
                    passthrough_args.append(token)
                index += 1

            if not parsed_package_ref:
                raise ValueError("未从命令中解析到技能包引用")

            return ParsedSkillInstallRequest(
                original_input=raw_input,
                package_ref=parsed_package_ref,
                skill_name=normalized_skill_name,
                passthrough_args=passthrough_args,
                used_legacy_install_alias=(action == "install"),
            )

        return ParsedSkillInstallRequest(
            original_input=raw_input,
            package_ref=raw_input,
            skill_name=normalized_skill_name,
        )

    def _looks_like_plain_skill_slug(self, package_ref: str) -> bool:
        """
        判断技能引用是否只是一个简短 slug。

        例如 `wechat-article-search` 这类值通常无法直接定位仓库，
        需要先通过 `npx skills find` 解析为 `owner/repo@skill`。
        """
        candidate = (package_ref or "").strip()
        if not candidate:
            return False
        if "://" in candidate or "/" in candidate or "@" in candidate:
            return False
        return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}", candidate))

    async def _resolve_package_ref_from_find(
        self,
        query: str,
        env: Dict[str, str],
        cwd: str,
    ) -> Optional[str]:
        """
        通过 `npx skills find` 解析完整技能引用。

        设计原因：
        - 历史对话摘要里常只留下 skill slug；
        - 但真正安装时通常需要 `owner/repo@skill` 这类完整引用。
        """
        refs = await self._find_package_refs(query=query, env=env, cwd=cwd)
        return refs[0] if refs else None

    async def _find_package_refs(
        self,
        query: str,
        env: Dict[str, str],
        cwd: str,
    ) -> List[str]:
        """
        调用 `npx skills find` 并提取所有可安装引用。

        设计原因：
        - 安装失败后需要基于真实 find 结果做候选回退；
        - 只返回结构化引用，避免上层再去解析大段终端文本。
        """
        find_command = ["npx", "skills", "find", query]
        logger.info(
            f"{Fore.CYAN}[SkillInstallerService] 调用 find 搜索技能候选: {' '.join(find_command)}{Style.RESET_ALL}"
        )
        cli_result = await self._run_command(
            command=find_command,
            env=env,
            cwd=cwd,
            timeout_seconds=min(self.timeout_seconds, 90),
        )
        if cli_result["return_code"] != 0:
            logger.warning(
                f"{Fore.YELLOW}[SkillInstallerService] find 命令执行失败，无法解析候选 | "
                f"query={query} | exit={cli_result['return_code']}{Style.RESET_ALL}"
            )
            return []

        combined_output = "\n".join(
            part
            for part in [cli_result.get("stdout", ""), cli_result.get("stderr", "")]
            if part
        )
        refs = self._extract_install_refs(combined_output)
        logger.info(
            f"{Fore.CYAN}[SkillInstallerService] find 结果解析完成 | "
            f"query={query} | candidates={refs[:5]}{Style.RESET_ALL}"
        )
        return refs

    def _build_install_command(self, parsed: ParsedSkillInstallRequest) -> List[str]:
        """
        生成最终执行的 Skills CLI 安装命令。

        说明：
        - 统一使用 `skills add`；
        - 默认追加 `-g -y`，让安装写入临时 `CODEX_HOME/skills`，同时避免交互确认阻塞。
        """
        command = ["npx", "skills", "add", parsed.package_ref]
        command.extend(parsed.passthrough_args)

        if not any(arg in {"-g", "--global"} for arg in command):
            command.append("-g")
        if not any(arg in {"-y", "--yes"} for arg in command):
            command.append("-y")

        # 若用户通过 package 直接传 URL / repo，但还单独给了 skill_name，
        # 这里补上 --skill，避免多技能仓库场景安装错误。
        if parsed.skill_name:
            has_skill_flag = any(
                arg == "--skill" or str(arg).startswith("--skill=")
                for arg in command
            )
            if not has_skill_flag and ("@" not in parsed.package_ref):
                command.extend(["--skill", parsed.skill_name])

        return command

    async def _attempt_recover_from_failed_install(
        self,
        parsed: ParsedSkillInstallRequest,
        cli_result: Dict[str, Any],
        env: Dict[str, str],
        cwd: str,
    ) -> Dict[str, Any]:
        """
        基于真实 `npx skills find` 结果尝试修正错误候选。

        恢复策略：
        1. 仅对“仓库鉴权失败 / 仓库不存在”这类高概率由错误候选引起的问题触发；
        2. 使用技能名 slug 重新检索真实候选；
        3. 只有当 find 返回了“同名 skill slug 的精确候选”时才自动重试安装，
           避免误装到语义相近但并非用户本意的其他技能。
        """
        failure_type = self._classify_cli_failure(cli_result)
        recovery_context: Dict[str, Any] = {
            "failure_type": failure_type,
            "retryable": failure_type in {"repository_auth_failed", "repository_not_found"},
            "queries": [],
            "candidate_package_refs": [],
            "retry_package_ref": None,
        }
        if not recovery_context["retryable"]:
            return recovery_context

        queries = self._build_recovery_queries(parsed)
        recovery_context["queries"] = queries
        if not queries:
            return recovery_context

        all_candidates: List[str] = []
        seen: set[str] = set()
        for query in queries:
            refs = await self._find_package_refs(query=query, env=env, cwd=cwd)
            for ref in refs:
                if ref == parsed.package_ref or ref in seen:
                    continue
                seen.add(ref)
                all_candidates.append(ref)

        recovery_context["candidate_package_refs"] = all_candidates[:5]
        if not all_candidates:
            logger.warning(
                f"{Fore.YELLOW}[SkillInstallerService] 安装失败后未从真实 find 结果中找到可替代候选 | "
                f"package_ref={parsed.package_ref}{Style.RESET_ALL}"
            )
            return recovery_context

        target_skill_name = self._normalize_name(
            parsed.skill_name or self._extract_skill_name_from_package_ref(parsed.package_ref)
        )
        for ref in all_candidates:
            candidate_skill_name = self._normalize_name(
                self._extract_skill_name_from_package_ref(ref)
            )
            if candidate_skill_name == target_skill_name:
                recovery_context["retry_package_ref"] = ref
                logger.warning(
                    f"{Fore.YELLOW}[SkillInstallerService] 命中同名精确候选，允许自动回退重试 | "
                    f"original={parsed.package_ref} | retry={ref}{Style.RESET_ALL}"
                )
                break

        return recovery_context

    async def _run_command(
        self,
        command: List[str],
        env: Dict[str, str],
        cwd: str,
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        """执行外部命令并返回结构化结果。"""
        start_time = time.time()
        rendered_command = " ".join(shlex.quote(part) for part in command)
        logger.info(
            f"{Fore.CYAN}[SkillInstallerService] 启动 Skills CLI 命令 | cwd={cwd} | cmd={rendered_command}{Style.RESET_ALL}"
        )

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )
        except FileNotFoundError:
            return {
                "success": False,
                "return_code": -1,
                "stdout": "",
                "stderr": "未找到 npx，可先检查 Node.js / npm 环境是否安装",
                "elapsed_ms": int((time.time() - start_time) * 1000),
                "command": rendered_command,
            }
        except Exception as exc:
            return {
                "success": False,
                "return_code": -1,
                "stdout": "",
                "stderr": f"启动 Skills CLI 命令失败: {exc}",
                "elapsed_ms": int((time.time() - start_time) * 1000),
                "command": rendered_command,
            }

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return {
                "success": False,
                "return_code": -9,
                "stdout": "",
                "stderr": f"命令执行超时（>{timeout_seconds}s）",
                "elapsed_ms": int((time.time() - start_time) * 1000),
                "command": rendered_command,
            }

        stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
        return_code = int(process.returncode or 0)
        elapsed_ms = int((time.time() - start_time) * 1000)

        if return_code == 0:
            logger.info(
                f"{Fore.GREEN}[SkillInstallerService] Skills CLI 命令执行成功 | "
                f"elapsed={elapsed_ms}ms | cmd={rendered_command}{Style.RESET_ALL}"
            )
        else:
            logger.warning(
                f"{Fore.YELLOW}[SkillInstallerService] Skills CLI 命令执行失败 | "
                f"exit={return_code} | elapsed={elapsed_ms}ms | cmd={rendered_command}{Style.RESET_ALL}"
            )
            if stderr_text:
                logger.warning(
                    f"{Fore.YELLOW}[SkillInstallerService] CLI stderr 摘要: "
                    f"{stderr_text[:240]}{Style.RESET_ALL}"
                )

        return {
            "success": return_code == 0,
            "return_code": return_code,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "elapsed_ms": elapsed_ms,
            "command": rendered_command,
        }

    def _locate_installed_skill_dir(
        self,
        skill_root: Path,
        preferred_skill_name: Optional[str],
        preferred_package_ref: str,
    ) -> Optional[Path]:
        """
        在临时 `CODEX_HOME/skills` 中定位刚安装的技能目录。

        这里使用 `rglob(SKILL.md)` 是为了兼容多层目录结构，
        避免未来 Skills CLI 组织方式轻微变化时立刻失效。
        """
        if not skill_root.exists():
            logger.warning(
                f"{Fore.YELLOW}[SkillInstallerService] 临时技能根目录不存在: {skill_root}{Style.RESET_ALL}"
            )
            return None

        candidate_dirs = sorted(
            {skill_file.parent for skill_file in skill_root.rglob(SKILL_FILE_NAME)}
        )
        if not candidate_dirs:
            return None

        if len(candidate_dirs) == 1:
            return candidate_dirs[0]

        normalized_targets = {
            self._normalize_name(preferred_skill_name),
            self._normalize_name(self._extract_skill_name_from_package_ref(preferred_package_ref)),
        }
        normalized_targets.discard("")

        for candidate_dir in candidate_dirs:
            candidate_dir_name = self._normalize_name(candidate_dir.name)
            declared_name = self._normalize_name(
                self._read_declared_skill_name(candidate_dir / SKILL_FILE_NAME)
            )
            if candidate_dir_name in normalized_targets or declared_name in normalized_targets:
                return candidate_dir

        logger.warning(
            f"{Fore.YELLOW}[SkillInstallerService] 发现多个技能目录但未能自动匹配，候选={candidate_dirs}{Style.RESET_ALL}"
        )
        return None

    def _infer_final_skill_name(
        self,
        installed_skill_dir: Path,
        preferred_skill_name: Optional[str],
    ) -> str:
        """
        生成最终复制到工作区的目录名。

        优先级：
        1. 显式传入的 skill_name
        2. SKILL.md frontmatter 中的 `name`
        3. 临时安装目录名
        """
        explicit_name = (preferred_skill_name or "").strip()
        if explicit_name:
            return explicit_name

        declared_name = self._read_declared_skill_name(installed_skill_dir / SKILL_FILE_NAME)
        if declared_name:
            return declared_name
        return installed_skill_dir.name

    def _read_declared_skill_name(self, skill_file: Path) -> Optional[str]:
        """从 SKILL.md frontmatter 中提取 `name` 字段。"""
        if not skill_file.exists():
            return None
        try:
            content = skill_file.read_text(encoding="utf-8")
        except Exception:
            return None
        match = FRONTMATTER_NAME_PATTERN.search(content)
        if not match:
            return None
        return match.group(1).strip() or None

    def _extract_skill_name_from_package_ref(self, package_ref: str) -> str:
        """
        从技能引用中提取技能名。

        示例：
        - `owner/repo@my-skill` -> `my-skill`
        - `my-skill` -> `my-skill`
        """
        candidate = (package_ref or "").strip()
        if "@" in candidate:
            return candidate.rsplit("@", 1)[-1].strip()
        if "/" in candidate:
            return candidate.rstrip("/").split("/")[-1].strip()
        return candidate

    def _normalize_name(self, value: Optional[str]) -> str:
        """统一目录名比较规则，避免连字符/下划线差异造成误判。"""
        return (value or "").strip().lower().replace("_", "-")

    def _extract_install_refs(self, text: str) -> List[str]:
        """从 CLI 输出中提取全部唯一的 `owner/repo@skill` 引用。"""
        refs: List[str] = []
        seen: set[str] = set()
        for match in INSTALL_REF_PATTERN.finditer(text or ""):
            ref = match.group(1).strip()
            if not ref or ref in seen:
                continue
            seen.add(ref)
            refs.append(ref)
        return refs

    def _build_recovery_queries(self, parsed: ParsedSkillInstallRequest) -> List[str]:
        """
        为失败恢复构建一组更稳妥的搜索词。

        说明：
        - 第一优先级使用技能名 slug，保证“同名技能”能被命中；
        - 再把连字符拆成自然语言短语，兼容 Skills CLI 的模糊搜索；
        - 最后补一个更短的主题短语，避免长 slug 没有命中时彻底失去回退机会。
        """
        skill_slug = (
            parsed.skill_name
            or self._extract_skill_name_from_package_ref(parsed.package_ref)
        ).strip()
        if not skill_slug:
            return []

        queries: List[str] = []
        seen: set[str] = set()

        def _append(candidate: str) -> None:
            normalized = candidate.strip().lower()
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            queries.append(candidate.strip())

        tokens = [token for token in re.split(r"[-_]+", skill_slug) if token]
        _append(skill_slug)
        if tokens:
            _append(" ".join(tokens))
        if len(tokens) >= 3:
            _append(" ".join(tokens[:3]))
        return queries[:3]

    def _classify_cli_failure(self, cli_result: Dict[str, Any]) -> str:
        """
        对 Skills CLI 失败做粗粒度分类，便于上层走不同恢复分支。
        """
        detail = "\n".join(
            str(part or "").strip()
            for part in [cli_result.get("stderr"), cli_result.get("stdout")]
            if str(part or "").strip()
        ).lower()
        if not detail:
            return "unknown"
        if "authentication failed" in detail or "private repository" in detail:
            return "repository_auth_failed"
        if "repository not found" in detail or "not found" in detail:
            return "repository_not_found"
        if "未找到 npx" in detail or "command not found" in detail:
            return "cli_not_available"
        if "超时" in detail or "timed out" in detail:
            return "timeout"
        return "unknown"

    def _build_recovery_fields(
        self,
        recovery_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """把恢复上下文压平成返回字段，便于 Agent 反思与重规划读取。"""
        if not recovery_context:
            return {
                "failure_type": None,
                "retryable": False,
                "recovery_queries": [],
                "suggested_package_refs": [],
                "recovered_by_find": False,
            }
        retry_package_ref = recovery_context.get("retry_package_ref")
        return {
            "failure_type": recovery_context.get("failure_type"),
            "retryable": bool(recovery_context.get("retryable", False)),
            "recovery_queries": list(recovery_context.get("queries") or []),
            "suggested_package_refs": list(
                recovery_context.get("candidate_package_refs") or []
            ),
            "recovered_by_find": bool(retry_package_ref),
        }

    def _format_cli_failure(
        self,
        parsed: ParsedSkillInstallRequest,
        cli_result: Dict[str, Any],
        recovery_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        生成更适合上层 Agent 读取的安装失败消息。

        这样 ExecutionEngine 在收集 `error` 时，就不会只看到
        “工具返回 success=false” 这种过于抽象的信息。
        """
        stderr_text = (cli_result.get("stderr") or "").strip()
        stdout_text = (cli_result.get("stdout") or "").strip()
        detail = stderr_text or stdout_text or "CLI 未返回可读错误信息"
        recovery_suffix = ""
        if recovery_context:
            failure_type = str(recovery_context.get("failure_type") or "").strip()
            candidate_refs = list(recovery_context.get("candidate_package_refs") or [])
            retry_package_ref = str(recovery_context.get("retry_package_ref") or "").strip()
            if failure_type == "repository_auth_failed":
                recovery_suffix += " 系统判断当前仓库可能是私有仓库，或当前环境缺少访问凭据。"
            elif failure_type == "repository_not_found":
                recovery_suffix += " 系统判断当前技能引用可能不存在或并非公开可安装引用。"

            if retry_package_ref:
                recovery_suffix += (
                    f" 系统已基于真实 `npx skills find` 结果自动回退重试候选 "
                    f"`{retry_package_ref}`，但仍未安装成功。"
                )
            elif candidate_refs:
                recovery_suffix += (
                    " 系统已基于真实 `npx skills find` 找到其他候选，可改试："
                    f"{', '.join(candidate_refs[:3])}。"
                )
            elif recovery_context.get("queries"):
                recovery_suffix += (
                    " 系统已尝试基于真实 `npx skills find` 搜索同名技能，但未找到可替代候选。"
                )

        if parsed.used_legacy_install_alias:
            return (
                "检测到历史命令 `npx skills install ...`，系统已自动转成 "
                "`npx skills add ...` 再尝试安装，但仍然失败。"
                f" 详细原因：{detail}{recovery_suffix}"
            )
        return f"Skills CLI 安装失败：{detail}{recovery_suffix}"
