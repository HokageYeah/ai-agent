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
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from colorama import Fore, Style
from loguru import logger

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
    r"\b(format|mkfs|diskpart)\b",   # 磁盘格式化类命令
    r"\bdd\s+if=",                   # dd 命令写入磁盘
    r">\s*/dev/sd",                  # 重定向写入磁盘设备
    r"\b(shutdown|reboot|poweroff|halt)\b",  # 系统电源操作
    r":\(\)\s*\{.*\};\s*:",          # Fork Bomb 模式
    r"\bsudo\s+rm\b",                # sudo rm（带权限递归删除）
    r"\bchmod\s+-R\s+777\b",         # 全局放开权限
]


class ShellExecutorTool(Tool):
    """
    Shell 命令执行工具

    继承自 Tool 抽象基类，提供安全可控的异步 Shell 命令执行功能。
    参考并增强 app/tools/example/shell.py 的 ExecTool 设计。

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

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        working_dir: Optional[str] = None,
        deny_patterns: Optional[List[str]] = None,
        allow_patterns: Optional[List[str]] = None,
        restrict_to_workspace: bool = False,
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
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

            if success:
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
                "working_dir": working_dir
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
