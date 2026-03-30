"""
Shell 命令执行工具模块

本模块实现了 ShellExecutorTool 类，提供安全可控的 Shell 命令执行功能。

功能特点：
1. 异步执行 Shell 命令，不阻塞事件循环
2. 危险命令拦截（黑名单正则模式防护）：
   - 禁止 rm -rf / del /f / rmdir /s 等递归删除
   - 禁止磁盘格式化 / dd 等破坏磁盘命令
   - 禁止 shutdown / reboot 等电源操作
   - 禁止 Fork Bomb
3. 可选白名单模式（仅允许特定命令模式）
4. 可选工作目录限制（restrict_to_workspace），防止路径遍历
5. 超时控制（默认 60 秒），超时自动 kill 进程
6. 输出截断保护（默认 10000 字符），防止超大输出淹没上下文
7. 分离 stdout / stderr，带返回码说明
8. 完整的 colorama 彩色中文日志

参考来源：
- 参考并移植 app/tools/example/shell.py 的 ExecTool 核心设计
- 符合本项目 BaseFileTool 的架构模式（ToolSchema / execute(params) 签名）

使用示例：
    tool = ShellExecutorTool()
    result = await tool.execute({
        "command": "ls -la /tmp",
        "working_dir": "/tmp"
    })
"""

import asyncio
import os
import re
import shlex
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from colorama import Fore, Style
from loguru import logger

from app.core.config import get_agent_workspace_dir
from app.tools.base import Tool, ToolSchema


# ──────────────────────────────────────────────────────────────
# 模块级常量
# ──────────────────────────────────────────────────────────────

# 默认命令超时时间（秒），超时后自动 kill 进程，防止挂起
DEFAULT_TIMEOUT = 60

# 输出截断阈值（字符数），超出时截断，防止 LLM 上下文溢出
DEFAULT_MAX_OUTPUT_CHARS = 10_000

# ──────────────────────────────────────────────────────────────
# 危险命令黑名单（正则模式列表）
# 移植自 shell.py 的 ExecTool，并补充了中文场景常见危险命令
# ──────────────────────────────────────────────────────────────
# NOTE: 每条正则都在 lower() 后的命令上匹配，大小写不敏感
_DEFAULT_DENY_PATTERNS: List[str] = [
    r"\brm\s+-[rf]{1,2}\b",           # rm -r / rm -rf / rm -fr（递归删除）
    r"\bdel\s+/[fq]\b",              # Windows del /f / del /q（强制删除）
    r"\brmdir\s+/s\b",               # Windows rmdir /s（递归删除目录）
    # NOTE:
    # - 旧规则 "\b(format|mkfs|diskpart)\b" 会误伤 URL 查询串（如 ?format=3）
    # - 这里改为“命令语义级”匹配：仅拦截真正的磁盘格式化命令，避免拦截天气等普通查询
    r"\bmkfs(?:\.[a-z0-9_+-]+)?\b",  # Linux mkfs / mkfs.ext4 等
    r"\bdiskpart\b",                 # Windows 磁盘分区工具
    r"(^|[\s;&|])format(?:\.com)?\s+[a-z]:",  # Windows format C:
    r"\bdd\s+if=",                   # dd 命令写入磁盘
    r">\s*/dev/sd",                  # 重定向写入磁盘设备
    r"\b(shutdown|reboot|poweroff|halt)\b",  # 系统电源操作
    r":\(\)\s*\{.*\};\s*:",          # Fork Bomb 模式
    r"\bsudo\s+rm\b",                # sudo rm（带权限递归删除）
    r"\bchmod\s+-R\s+777\b",         # 全局放开权限
]

# 统一把 `npx skills ...` 规范化为 `npx --yes skills ...`，避免首次执行时卡在
# “Need to install the following packages ... Ok to proceed? (y)” 交互提示。
_NPX_SKILLS_COMMAND_PATTERN = re.compile(
    r"(?<![\w-])npx(?!\s+(?:-y|--yes)\b)\s+skills\b"
)


class ShellExecutorTool(Tool):
    """
    Shell 命令执行工具

    继承自 Tool 抽象基类，提供安全可控的异步 Shell 命令执行功能。
    参考并增强 app/tools/example/shell.py 的 ExecTool 设计。

    planning_safe = False：
        Shell 命令可能创建/修改/删除文件、启动进程、改变系统状态，
        属于不确定性副作用工具，必须在 Execution Node 内执行。

    安全机制：
    1. 黑名单模式拦截（deny_patterns 正则列表）
    2. 白名单模式限制（allow_patterns，可选）
    3. 工作目录限制（restrict_to_workspace，防止路径遍历）
    4. 超时控制（超时 kill 进程）
    5. 输出截断保护

    属性：
        name:        工具名称，固定为 "shell_exec"
        description: 工具描述
    """

    # 有副作用——可执行任意 shell 命令，禁止在 Planning tool-calling loop 中调用
    planning_safe: bool = False

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        working_dir: Optional[str] = None,
        deny_patterns: Optional[List[str]] = None,
        allow_patterns: Optional[List[str]] = None,
        restrict_to_workspace: bool = False,
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
        skill_installer: Optional[Any] = None,
    ):
        """
        初始化 ShellExecutorTool

        Args:
            timeout:               命令超时时间（秒），默认 60
            working_dir:           默认工作目录，None 则使用当前目录
            deny_patterns:         危险命令黑名单正则列表，None 则使用内置默认列表
            allow_patterns:        命令白名单正则列表（非空时仅允许匹配的命令）
            restrict_to_workspace: 是否将命令中的绝对路径限制在工作目录内
            max_output_chars:      输出最大字符数，超出截断
        """
        self._name         = "shell_exec"
        self._description  = (
            "执行 Shell 命令，并返回标准输出和标准错误。"
            "支持常见 Unix/macOS Shell 命令。"
            "危险命令（如 rm -rf、格式化、关机等）会被自动拦截，请勿尝试。"
        )
        self._timeout             = timeout
        self._working_dir         = working_dir
        self._deny_patterns       = deny_patterns if deny_patterns is not None else _DEFAULT_DENY_PATTERNS
        self._allow_patterns      = allow_patterns or []
        self._restrict_workspace  = restrict_to_workspace
        self._max_output_chars    = max_output_chars
        self._skill_installer     = skill_installer

        logger.info(
            f"{Fore.CYAN}[ShellExecutorTool] Shell 命令执行工具初始化完成 "
            f"| 超时={timeout}s "
            f"| 黑名单规则={len(self._deny_patterns)}条 "
            f"| 工作目录限制={'开启' if restrict_to_workspace else '关闭'} "
            f"| 输出截断={max_output_chars}字符{Style.RESET_ALL}"
        )

    @property
    def name(self) -> str:
        """获取工具名称（固定为 "shell_exec"）"""
        return self._name

    @property
    def schema(self) -> ToolSchema:
        """
        获取工具 Schema

        参数规范：
        - command:     要执行的 Shell 命令（必需）
        - working_dir: 命令执行的工作目录（可选，默认使用初始化时指定的目录）
        - timeout:     本次执行超时时间（可选，覆盖默认值）
        - env:         额外的环境变量键值对（可选）

        Returns:
            ToolSchema: 工具参数 Schema
        """
        return ToolSchema(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type":        "string",
                        "description": "要执行的 Shell 命令，如 'ls -la /tmp' 或 'echo Hello'"
                    },
                    "working_dir": {
                        "type":        "string",
                        "description": "命令执行的工作目录（绝对路径），留空则使用默认目录"
                    },
                    "timeout": {
                        "type":        "integer",
                        "description": f"本次执行超时时间（秒），留空则使用默认值 {self._timeout}",
                        "minimum":     1,
                        "maximum":     600
                    },
                    "env": {
                        "type":                 "object",
                        "description":          "额外的环境变量键值对，将与系统环境变量合并",
                        "additionalProperties": {"type": "string"}
                    }
                },
                "required":             ["command"],
                "additionalProperties": False
            }
        )

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行 Shell 命令

        完整执行流程：
        1. 提取参数（command / working_dir / timeout / env）
        2. 安全守卫：黑名单拦截 → 白名单过滤 → 路径遍历检测
        3. 准备工作目录和环境变量
        4. 异步子进程启动（asyncio.create_subprocess_shell）
        5. 等待执行完成（含超时控制）
        6. 分离解析 stdout / stderr / returncode
        7. 超长输出截断保护
        8. 返回结构化结果

        Args:
            params: 参数字典，必须包含 "command" 键

        Returns:
            Dict[str, Any]: 执行结果，包含：
                - success:       是否执行成功（returncode == 0）
                - command:       执行的命令
                - stdout:        标准输出文本
                - stderr:        标准错误文本
                - return_code:   进程退出码
                - elapsed_ms:    执行耗时（毫秒）
                - truncated:     输出是否被截断
                - working_dir:   实际工作目录
                - error:         错误信息（失败时存在）
        """
        # ═══════════════ 参数提取 ═══════════════
        command     = params.get("command", "").strip()
        working_dir = params.get("working_dir") or self._working_dir or os.getcwd()
        timeout     = params.get("timeout", self._timeout)
        extra_env   = params.get("env", {}) or {}

        # ── 命令非空校验 ──
        if not command:
            logger.warning(
                f"{Fore.YELLOW}[ShellExecutorTool] 命令为空，拒绝执行{Style.RESET_ALL}"
            )
            return {"success": False, "error": "命令不能为空"}

        normalized_command = self._rewrite_npx_skills_command(command)
        if normalized_command != command:
            logger.info(
                f"{Fore.CYAN}[ShellExecutorTool] 检测到 Skills CLI 命令，"
                f"已自动补齐 npx 的非交互 `--yes` 参数{Style.RESET_ALL}"
            )
            command = normalized_command

        proxy_request = self._extract_skills_install_proxy_request(command)
        if proxy_request is not None:
            logger.info(
                f"{Fore.CYAN}[ShellExecutorTool] 检测到原始 Skills CLI 安装命令，"
                f"将自动代理到结构化 skill_install 服务执行 | "
                f"package={proxy_request['package']} | "
                f"skill_name={proxy_request.get('skill_name') or '自动识别'}{Style.RESET_ALL}"
            )
            return await self._proxy_skills_install_command(
                original_command=command,
                working_dir=working_dir,
                timeout=int(timeout),
                package=proxy_request["package"],
                skill_name=proxy_request.get("skill_name"),
            )

        # ── 规范化 skillhub 安装命令的目标目录 ──
        # 当命令形如 `skillhub install xxx` 且未显式提供 --dir 时，
        # 自动注入 `--dir <AGENT_WORKSPACE_DIR>`，避免技能被安装到项目根 `./skills`。
        normalized_command = self._rewrite_skillhub_install_command(command)
        if normalized_command != command:
            logger.info(
                f"{Fore.CYAN}[ShellExecutorTool] 检测到 skillhub 安装命令，"
                f"已自动注入 --dir 指向 Agent 工作区{Style.RESET_ALL}"
            )
            command = normalized_command

        logger.info(
            f"{Fore.CYAN}[ShellExecutorTool] 准备执行命令 "
            f"| cmd='{command[:80]}{'...' if len(command) > 80 else ''}' "
            f"| cwd={working_dir} "
            f"| timeout={timeout}s{Style.RESET_ALL}"
        )

        # ═══════════════ 安全守卫 ═══════════════
        guard_error = self._guard_command(command, working_dir)
        if guard_error:
            logger.warning(
                f"{Fore.YELLOW}[ShellExecutorTool] 命令被安全守卫拦截: {guard_error} "
                f"| cmd='{command}'{Style.RESET_ALL}"
            )
            return {
                "success": False,
                "error":   guard_error,
                "command": command
            }

        # ═══════════════ 工作目录和环境变量准备 ═══════════════
        # 确保工作目录存在（不存在时降级为当前目录，避免崩溃）
        cwd_path = Path(working_dir)
        if not cwd_path.exists() or not cwd_path.is_dir():
            logger.warning(
                f"{Fore.YELLOW}[ShellExecutorTool] 工作目录不存在: {working_dir}，"
                f"降级为当前目录{Style.RESET_ALL}"
            )
            working_dir = os.getcwd()

        # 合并系统环境变量与用户自定义环境变量
        exec_env = {**os.environ, **{k: str(v) for k, v in extra_env.items()}}

        # ═══════════════ 异步子进程执行 ═══════════════
        start_time = time.time()
        try:
            logger.debug(
                f"{Fore.BLUE}[ShellExecutorTool] 启动子进程: {command[:100]}{Style.RESET_ALL}"
            )
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                env=exec_env
            )

            # ── 等待执行完成（带超时控制）──
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                # 超时：强制 kill 进程，防止僵尸进程
                process.kill()
                await process.wait()  # 确保进程资源已回收
                elapsed_ms = int((time.time() - start_time) * 1000)
                logger.error(
                    f"{Fore.RED}[ShellExecutorTool] 命令执行超时（>{timeout}s）: "
                    f"'{command[:60]}'{Style.RESET_ALL}"
                )
                return {
                    "success":     False,
                    "error":       f"命令执行超时（超过 {timeout} 秒），进程已强制终止",
                    "command":     command,
                    "elapsed_ms":  elapsed_ms,
                    "working_dir": working_dir
                }

            elapsed_ms  = int((time.time() - start_time) * 1000)
            return_code = process.returncode

            # ═══════════════ 输出解析 ═══════════════
            # 解码 stdout（容忍解码错误，防止特殊字符导致崩溃）
            stdout_text = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            stderr_text = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

            # 超长输出截断保护（stdout + stderr 分别独立截断）
            truncated = False
            if len(stdout_text) > self._max_output_chars:
                truncated   = True
                omitted     = len(stdout_text) - self._max_output_chars
                stdout_text = (
                    stdout_text[:self._max_output_chars]
                    + f"\n...（stdout 已截断，省略 {omitted} 字符）"
                )
            if stderr_text and len(stderr_text) > self._max_output_chars:
                truncated   = True
                stderr_text = stderr_text[:self._max_output_chars] + "\n...（stderr 已截断）"

            # ── 根据 returncode 决定 success ──
            success = (return_code == 0)
            idempotent_hit = False

            # 对 `skillhub install` 做幂等容错：
            # 若 CLI 返回 "Target exists" 且目标目录下已有 SKILL.md，
            # 视为“已安装完成”，避免把重复安装误判为失败。
            if not success:
                idempotent_hit = self._is_skillhub_install_already_satisfied(
                    command=command,
                    stdout_text=stdout_text,
                    stderr_text=stderr_text,
                    working_dir=working_dir,
                )
                if idempotent_hit:
                    success = True

            if success:
                if idempotent_hit:
                    logger.info(
                        f"{Fore.GREEN}[ShellExecutorTool] 命中安装幂等场景：目标已存在且可用，"
                        f"按成功处理 | returncode={return_code} | 耗时={elapsed_ms}ms{Style.RESET_ALL}"
                    )
                else:
                    logger.info(
                        f"{Fore.GREEN}[ShellExecutorTool] 命令执行成功 "
                        f"| returncode={return_code} "
                        f"| 耗时={elapsed_ms}ms "
                        f"| stdout={len(stdout_text)}字符 "
                        f"| stderr={len(stderr_text)}字符 "
                        f"| 截断={truncated}{Style.RESET_ALL}"
                    )
            else:
                logger.warning(
                    f"{Fore.YELLOW}[ShellExecutorTool] 命令以非零码退出 "
                    f"| returncode={return_code} "
                    f"| 耗时={elapsed_ms}ms{Style.RESET_ALL}"
                )
                if stderr_text.strip():
                    logger.debug(
                        f"{Fore.YELLOW}[ShellExecutorTool] stderr: "
                        f"{stderr_text[:200]}{Style.RESET_ALL}"
                    )

            return {
                "success":     success,
                "command":     command,
                "stdout":      stdout_text,
                "stderr":      stderr_text,
                "return_code": return_code,
                "elapsed_ms":  elapsed_ms,
                "truncated":   truncated,
                "working_dir": working_dir,
                "idempotent":  idempotent_hit,
            }

        except FileNotFoundError:
            # NOTE: Shell 本身找不到时（极少见，通常是系统环境问题）
            logger.error(
                f"{Fore.RED}[ShellExecutorTool] Shell 可执行文件未找到{Style.RESET_ALL}"
            )
            return {
                "success": False,
                "error":   "无法启动 Shell 进程（Shell 可执行文件未找到）",
                "command": command
            }
        except PermissionError as e:
            logger.error(
                f"{Fore.RED}[ShellExecutorTool] 权限错误: {e}{Style.RESET_ALL}"
            )
            return {
                "success": False,
                "error":   f"权限不足，无法执行命令: {e}",
                "command": command
            }
        except Exception as e:
            logger.exception(
                f"{Fore.RED}[ShellExecutorTool] 命令执行发生未知错误: {e}{Style.RESET_ALL}"
            )
            return {
                "success": False,
                "error":   f"命令执行失败: {e}",
                "command": command
            }

    def _get_skill_installer(self, timeout_seconds: int):
        """
        延迟获取技能安装服务。

        设计原因：
        - Shell 工具本身是通用能力，不应在模块加载时强耦合安装服务；
        - 仅当检测到原始 `npx skills add/install` 命令时，才需要走统一安装代理；
        - 同时便于测试时注入桩对象，验证代理行为而不触发真实安装。
        """
        installer = self._skill_installer
        if installer is not None and getattr(installer, "timeout_seconds", timeout_seconds) == timeout_seconds:
            return installer

        from app.skills.installer import SkillInstallerService

        installer = SkillInstallerService(timeout_seconds=timeout_seconds)
        self._skill_installer = installer
        return installer

    async def _proxy_skills_install_command(
        self,
        *,
        original_command: str,
        working_dir: str,
        timeout: int,
        package: str,
        skill_name: Optional[str],
    ) -> Dict[str, Any]:
        """
        把原始 Skills CLI 安装命令代理到统一安装服务。

        设计原因：
        - 历史技能与模型仍可能产出 `shell_exec("npx skills add ...")`；
        - 若继续走原始 shell，容易再次落入交互安装、网络挂起、超时难观测等问题；
        - 因此在 Shell 公共层把“安装技能包”的命令收口到 `SkillInstallerService`，
          让其复用统一的预热、候选回退、工作区落地与幂等逻辑。
        """
        installer = self._get_skill_installer(timeout_seconds=max(1, int(timeout)))
        start_time = time.time()
        result = await installer.install(
            package=package,
            skill_name=skill_name,
            overwrite=False,
        )
        elapsed_ms = int((time.time() - start_time) * 1000)

        success = bool(result.get("success"))
        stderr_text = ""
        if not success:
            stderr_text = str(result.get("error") or result.get("stderr") or "").strip()

        stdout_text = str(
            result.get("message")
            or result.get("stdout")
            or result.get("installed_path")
            or ""
        ).strip()

        proxied_result: Dict[str, Any] = {
            "success": success,
            "command": original_command,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "return_code": 0 if success else 1,
            "elapsed_ms": elapsed_ms,
            "truncated": False,
            "working_dir": working_dir,
            "proxied_to_skill_install": True,
            "skill_install_result": result,
        }
        if not success:
            proxied_result["error"] = stderr_text or "技能安装失败"
        return proxied_result

    def _rewrite_npx_skills_command(self, command: str) -> str:
        """
        把 `npx skills ...` 统一改写为 `npx --yes skills ...`。

        设计原因：
        - 某些技能会通过 `shell_exec` 直接执行 `npx skills find/add`；
        - 若环境中尚未缓存 `skills` CLI，npx 会先弹出依赖安装确认提示；
        - Shell 工具无法与该交互提示对话，只会最终表现为“命令超时”；
        - 因此在公共 Shell 层统一补齐 `--yes`，保证所有 Skills CLI 命令
          都默认走非交互路径，而不是只修当前某一个技能。
        """
        raw_command = (command or "").strip()
        if not raw_command:
            return raw_command
        return _NPX_SKILLS_COMMAND_PATTERN.sub("npx --yes skills", raw_command)

    def _extract_skills_install_proxy_request(self, command: str) -> Optional[Dict[str, Any]]:
        """
        从 shell 命令中提取“Skills CLI 安装请求”。

        只识别 `npx skills add/install ...` 或 `skills add/install ...` 语义。
        `skills find` 属于只读搜索，不应代理到安装服务。
        """
        raw_command = (command or "").strip()
        if not raw_command:
            return None

        try:
            tokens = shlex.split(raw_command)
        except ValueError:
            return None
        if not tokens:
            return None

        control_tokens = {"&&", "||", ";", "|"}
        for index, token in enumerate(tokens):
            executable = Path(token).name.lower()
            cursor = index
            if executable == "npx":
                cursor += 1
                while cursor < len(tokens) and tokens[cursor] in {"-y", "--yes"}:
                    cursor += 1
                if cursor >= len(tokens):
                    continue
                executable = Path(tokens[cursor]).name.lower()
            if executable != "skills":
                continue

            action_idx = cursor + 1
            if action_idx >= len(tokens):
                continue
            action = tokens[action_idx].strip().lower()
            if action not in {"add", "install"}:
                continue

            package_ref: Optional[str] = None
            skill_name: Optional[str] = None
            arg_idx = action_idx + 1
            while arg_idx < len(tokens):
                current = tokens[arg_idx]
                if current in control_tokens:
                    break
                if current.startswith(">") or current.startswith("<") or re.fullmatch(r"\d+>&\d+", current):
                    arg_idx += 1
                    continue
                if current == "--skill" and arg_idx + 1 < len(tokens):
                    skill_name = tokens[arg_idx + 1].strip() or skill_name
                    arg_idx += 2
                    continue
                if current.startswith("--skill="):
                    skill_name = current.split("=", 1)[1].strip() or skill_name
                    arg_idx += 1
                    continue
                if current.startswith("-"):
                    arg_idx += 1
                    continue
                if package_ref is None:
                    package_ref = current.strip()
                    arg_idx += 1
                    continue
                arg_idx += 1

            if package_ref:
                return {
                    "package": package_ref,
                    "skill_name": skill_name,
                }

        return None

    def _rewrite_skillhub_install_command(self, command: str) -> str:
        """
        为 `skillhub install` 命令注入 `--dir <workspace>`。

        只在“单条简单命令”场景下做重写，避免破坏复杂 shell 语句。
        """
        raw_command = (command or "").strip()
        if not raw_command:
            return raw_command

        # 遇到复合 shell 表达式时保守跳过，避免改写语义。
        if any(token in raw_command for token in ["&&", "||", "|", ";", "$(", "`"]):
            return raw_command

        try:
            tokens = shlex.split(raw_command)
        except ValueError:
            return raw_command
        if not self._is_skillhub_install_tokens(tokens):
            return raw_command
        if any(token == "--dir" or token.startswith("--dir=") for token in tokens):
            return raw_command

        workspace_dir = str(get_agent_workspace_dir())
        rewritten_tokens = [tokens[0], "--dir", workspace_dir, *tokens[1:]]
        return shlex.join(rewritten_tokens)

    def _is_skillhub_install_tokens(self, tokens: List[str]) -> bool:
        """判断命令 token 是否为 `skillhub install ...`。"""
        if not tokens:
            return False
        executable = Path(tokens[0]).name.lower()
        if executable != "skillhub":
            return False
        return "install" in tokens

    def _is_skillhub_install_already_satisfied(
        self,
        command: str,
        stdout_text: str,
        stderr_text: str,
        working_dir: str,
    ) -> bool:
        """
        检测 `skillhub install` 的“目录已存在”幂等场景。

        只有当：
        1. 输出里明确出现 Target exists / already exists
        2. 且目标目录下存在 SKILL.md
        才会按成功处理。
        """
        try:
            tokens = shlex.split(command)
        except ValueError:
            return False
        if not self._is_skillhub_install_tokens(tokens):
            return False

        combined = "\n".join([stderr_text or "", stdout_text or ""]).lower()
        if ("target exists" not in combined) and ("already exists" not in combined):
            return False

        target_path = self._extract_target_exists_path(stderr_text) or self._extract_target_exists_path(stdout_text)
        if target_path:
            candidate_dir = Path(target_path).expanduser()
        else:
            candidate_dir = self._infer_skillhub_target_dir_from_command(
                command=command,
                working_dir=working_dir,
            )
        if candidate_dir is None:
            return False

        candidate_dir = candidate_dir.resolve(strict=False)
        skill_file = candidate_dir / "SKILL.md"
        if skill_file.exists():
            logger.info(
                f"{Fore.GREEN}[ShellExecutorTool] 检测到技能目录已存在且包含 SKILL.md："
                f"{candidate_dir}，按已安装成功处理{Style.RESET_ALL}"
            )
            return True
        return False

    def _extract_target_exists_path(self, text: str) -> Optional[str]:
        """从 CLI 输出中提取 `Target exists: <path>` 的路径。"""
        if not text:
            return None
        match = re.search(r"Target exists:\s*(.+)", text)
        if not match:
            return None
        return match.group(1).strip()

    def _infer_skillhub_target_dir_from_command(
        self,
        command: str,
        working_dir: str,
    ) -> Optional[Path]:
        """
        根据 `skillhub install` 命令推断目标目录。

        推断规则：
        - 若显式传了 --dir，则目标是 `<dir>/<slug>`
        - 否则默认 `<working_dir>/skills/<slug>`
        """
        try:
            tokens = shlex.split(command)
        except ValueError:
            return None
        if not self._is_skillhub_install_tokens(tokens):
            return None

        install_idx = tokens.index("install")
        slug = None
        for candidate in tokens[install_idx + 1 :]:
            if candidate.startswith("-"):
                continue
            slug = candidate.strip()
            break
        if not slug:
            return None

        install_root: Optional[Path] = None
        for idx, token in enumerate(tokens):
            if token == "--dir" and idx + 1 < len(tokens):
                install_root = Path(tokens[idx + 1].strip()).expanduser()
                break
            if token.startswith("--dir="):
                install_root = Path(token.split("=", 1)[1].strip()).expanduser()
                break

        if install_root is None:
            install_root = Path(working_dir) / "skills"
        elif not install_root.is_absolute():
            install_root = (Path(working_dir) / install_root).resolve(strict=False)

        return install_root / slug

    def _guard_command(self, command: str, cwd: str) -> Optional[str]:
        """
        命令安全守卫

        依次执行三层安全检测（移植并增强自 shell.py ExecTool._guard_command）：
        1. 黑名单正则检测：匹配到危险模式则立即拒绝
        2. 白名单正则检测：若设置了白名单，命令必须匹配至少一条才允许
        3. 路径遍历检测：若开启工作目录限制，命令中的绝对路径不能超出 cwd

        Args:
            command: 待检测的 Shell 命令字符串
            cwd:     当前工作目录（用于路径遍历检测）

        Returns:
            Optional[str]: 若检测通过返回 None；若被拦截返回错误描述字符串
        """
        cmd_lower = command.strip().lower()

        # ── 第一层：黑名单模式检测（危险命令拦截）──
        for pattern in self._deny_patterns:
            if re.search(pattern, cmd_lower):
                logger.warning(
                    f"{Fore.YELLOW}[ShellExecutorTool] 黑名单拦截，"
                    f"匹配规则: '{pattern}' "
                    f"| 命令: '{command[:60]}'{Style.RESET_ALL}"
                )
                return (
                    f"命令被安全守卫拦截（匹配危险模式: {pattern}），"
                    "禁止执行可能破坏系统的命令"
                )

        # ── 第二层：白名单模式过滤（仅当 allow_patterns 非空时生效）──
        if self._allow_patterns:
            if not any(re.search(p, cmd_lower) for p in self._allow_patterns):
                logger.warning(
                    f"{Fore.YELLOW}[ShellExecutorTool] 白名单过滤，"
                    f"命令未匹配任何允许模式 "
                    f"| 命令: '{command[:60]}'{Style.RESET_ALL}"
                )
                return "命令被安全守卫拦截（不在白名单内），只允许执行预定义的命令模式"

        # ── 第三层：路径遍历检测（仅当 restrict_to_workspace=True 时生效）──
        if self._restrict_workspace:
            # 检查命令字符串本身是否包含 ../ 路径遍历
            if "../" in command or "..\\" in command:
                return "命令被安全守卫拦截（检测到路径遍历 '../'），不允许跳出工作目录"

            cwd_resolved = Path(cwd).resolve()

            # 提取命令中的绝对路径（POSIX 格式）
            posix_paths = re.findall(r"(?:^|[\s|>])(/[^\s\"'>]+)", command)
            # 提取命令中的绝对路径（Windows 格式，如 C:\path）
            win_paths   = re.findall(r"[A-Za-z]:\\[^\\\"']+", command)

            for raw_path in posix_paths + win_paths:
                try:
                    target = Path(raw_path.strip()).resolve()
                except Exception:
                    continue
                # 检测绝对路径是否超出工作目录范围
                if target.is_absolute() and cwd_resolved not in target.parents and target != cwd_resolved:
                    logger.warning(
                        f"{Fore.YELLOW}[ShellExecutorTool] 路径越界检测: "
                        f"'{target}' 超出工作目录 '{cwd_resolved}'{Style.RESET_ALL}"
                    )
                    return (
                        f"命令被安全守卫拦截（路径 '{raw_path.strip()}' 超出工作目录 '{cwd}'），"
                        "开启了工作目录限制模式"
                    )

        # 三层检测均通过
        return None


# ──────────────────────────────────────────────────────────────
# 便捷函数：快速执行 Shell 命令
# ──────────────────────────────────────────────────────────────

async def quick_shell(
    command: str,
    working_dir: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT
) -> Dict[str, Any]:
    """
    便捷 Shell 命令执行函数

    使用默认安全配置执行命令，适合简单、快速地在代码中调用 Shell。

    Args:
        command:     Shell 命令字符串
        working_dir: 工作目录（可选）
        timeout:     超时时间（可选）

    Returns:
        Dict[str, Any]: 执行结果
    """
    tool = ShellExecutorTool()
    return await tool.execute({
        "command":     command,
        "working_dir": working_dir,
        "timeout":     timeout
    })
