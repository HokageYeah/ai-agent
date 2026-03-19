"""
ShellExecutorTool 测试
======================

重点覆盖：
1. `skillhub install` 自动注入 `--dir <AGENT_WORKSPACE_DIR>`
2. 目标目录已存在（Target exists）时的幂等成功判定
"""

import shlex

import pytest

from app.tools.builtin.shell import ShellExecutorTool


class _FakeProcess:
    """用于替代 asyncio 子进程对象的轻量桩。"""

    def __init__(self, returncode: int, stdout: bytes = b"", stderr: bytes = b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        return None

    async def wait(self):
        return None


@pytest.mark.asyncio
async def test_shell_exec_should_inject_dir_for_skillhub_install(monkeypatch, tmp_path):
    """`skillhub install` 未带 --dir 时，应自动注入工作区目录。"""
    workspace_dir = tmp_path / "skills_md"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    captured = {}

    async def fake_create_subprocess_shell(command, stdout, stderr, cwd, env):
        captured["command"] = command
        captured["cwd"] = cwd
        return _FakeProcess(returncode=0, stdout=b"ok", stderr=b"")

    monkeypatch.setattr(
        "app.tools.builtin.shell.get_agent_workspace_dir",
        lambda: workspace_dir,
    )
    monkeypatch.setattr(
        "app.tools.builtin.shell.asyncio.create_subprocess_shell",
        fake_create_subprocess_shell,
    )

    tool = ShellExecutorTool()
    result = await tool.execute(
        {
            "command": "skillhub install browser-use",
            "working_dir": str(tmp_path),
        }
    )

    tokens = shlex.split(captured["command"])
    assert result["success"] is True
    assert tokens[:4] == ["skillhub", "--dir", str(workspace_dir), "install"]
    assert tokens[4] == "browser-use"


@pytest.mark.asyncio
async def test_shell_exec_should_treat_target_exists_as_success(monkeypatch, tmp_path):
    """当 CLI 返回 Target exists 且目录可用时，应按成功处理。"""
    workspace_dir = tmp_path / "skills_md"
    skill_dir = workspace_dir / "browser-use"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: browser-use\ndescription: test\n---\n",
        encoding="utf-8",
    )

    async def fake_create_subprocess_shell(command, stdout, stderr, cwd, env):
        return _FakeProcess(
            returncode=1,
            stdout=b"",
            stderr=f"Error: Target exists: {skill_dir}".encode("utf-8"),
        )

    monkeypatch.setattr(
        "app.tools.builtin.shell.get_agent_workspace_dir",
        lambda: workspace_dir,
    )
    monkeypatch.setattr(
        "app.tools.builtin.shell.asyncio.create_subprocess_shell",
        fake_create_subprocess_shell,
    )

    tool = ShellExecutorTool()
    result = await tool.execute(
        {
            "command": "skillhub install browser-use",
            "working_dir": str(tmp_path),
        }
    )

    assert result["success"] is True
    assert result["idempotent"] is True
