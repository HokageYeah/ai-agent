"""
技能安装工具测试
================

重点验证：
1. SkillManager 默认会读取配置化的 Agent 工作区。
2. 技能安装服务会把历史 `install` 写法规范化为 `add`。
3. 安装成功后，技能会被复制到项目工作区，而不是停留在临时 `CODEX_HOME`。
"""

from pathlib import Path

import pytest

from app.agents.library import GENERAL_AGENT
from app.core.config import settings
from app.skills.installer import SkillInstallerService
from app.skills.manager import SkillManager


def test_skill_manager_should_use_configured_workspace(tmp_path, monkeypatch):
    """未显式传 skills_root 时，应走统一配置的 Agent 工作区。"""
    monkeypatch.setattr(settings, "AGENT_WORKSPACE_DIR", str(tmp_path))

    manager = SkillManager(auto_discover=False)

    assert manager.skills_root == tmp_path.resolve()


def test_normalize_request_should_convert_legacy_install_alias():
    """历史 `npx skills install` 写法应被规范化为 add 语义。"""
    service = SkillInstallerService(workspace_dir=Path.cwd() / "app/skills/skills_md")

    parsed = service._normalize_request(
        package="npx skills install demo/repo@wechat-article-search",
        skill_name=None,
    )

    assert parsed.package_ref == "demo/repo@wechat-article-search"
    assert parsed.used_legacy_install_alias is True


def test_general_agent_should_expose_skill_install_tool():
    """通用助手应能直接使用 skill_install 工具处理安装任务。"""
    assert "skill_install" in GENERAL_AGENT.available_tools


@pytest.mark.asyncio
async def test_install_should_copy_skill_into_workspace(tmp_path, monkeypatch):
    """安装成功后，应把技能复制到配置工作区。"""
    workspace_dir = tmp_path / "skills_md"
    service = SkillInstallerService(workspace_dir=workspace_dir)

    async def fake_run_command(command, env, cwd, timeout_seconds):
        skill_dir = Path(env["CODEX_HOME"]) / "skills" / "wechat-article-search"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: wechat-article-search\ndescription: 测试技能\n---\n",
            encoding="utf-8",
        )
        (skill_dir / "README.md").write_text("# demo\n", encoding="utf-8")
        return {
            "success": True,
            "return_code": 0,
            "stdout": "installed",
            "stderr": "",
            "elapsed_ms": 10,
            "command": " ".join(command),
        }

    async def fake_resolve_package_ref_from_find(query, env, cwd):
        return "demo/repo@wechat-article-search"

    monkeypatch.setattr(service, "_run_command", fake_run_command)
    monkeypatch.setattr(
        service,
        "_resolve_package_ref_from_find",
        fake_resolve_package_ref_from_find,
    )

    result = await service.install(
        package="npx skills install wechat-article-search",
        overwrite=False,
    )

    target_dir = workspace_dir / "wechat-article-search"
    assert result["success"] is True
    assert result["resolved_package_ref"] == "demo/repo@wechat-article-search"
    assert result["used_legacy_install_alias"] is True
    assert target_dir.exists()
    assert (target_dir / "SKILL.md").exists()
    assert (target_dir / "README.md").exists()


@pytest.mark.asyncio
async def test_install_should_detect_skill_from_global_agents_dir(tmp_path, monkeypatch):
    """
    Skills CLI 新版会把全局通用技能写入 `$HOME/.agents/skills`。

    这个测试用于覆盖本次线上报错场景：
    命令执行成功，但旧逻辑只查 `CODEX_HOME/skills`，导致误判“未找到技能包”。
    """
    workspace_dir = tmp_path / "skills_md"
    service = SkillInstallerService(workspace_dir=workspace_dir)
    captured_env = {}

    async def fake_run_command(command, env, cwd, timeout_seconds):
        captured_env.update(env)
        skill_dir = Path(env["HOME"]) / ".agents" / "skills" / "wechat-article-search"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: wechat-article-search\ndescription: 全局技能目录测试\n---\n",
            encoding="utf-8",
        )
        (skill_dir / "notes.txt").write_text("ok\n", encoding="utf-8")
        return {
            "success": True,
            "return_code": 0,
            "stdout": "installed",
            "stderr": "",
            "elapsed_ms": 10,
            "command": " ".join(command),
        }

    monkeypatch.setattr(service, "_run_command", fake_run_command)

    result = await service.install(
        package="wuchubuzai2018/expert-skills-hub@wechat-article-search",
        overwrite=False,
    )

    target_dir = workspace_dir / "wechat-article-search"
    assert result["success"] is True
    assert captured_env["HOME"] == captured_env["CODEX_HOME"]
    assert target_dir.exists()
    assert (target_dir / "SKILL.md").exists()
    assert (target_dir / "notes.txt").exists()


@pytest.mark.asyncio
async def test_install_should_retry_with_real_find_candidate_after_auth_failure(
    tmp_path,
    monkeypatch,
):
    """首次仓库鉴权失败后，应基于真实 find 结果回退到同名公开候选。"""
    workspace_dir = tmp_path / "skills_md"
    service = SkillInstallerService(workspace_dir=workspace_dir)

    async def fake_run_command(command, env, cwd, timeout_seconds):
        rendered = " ".join(command)
        if command[:3] == ["npx", "skills", "find"]:
            return {
                "success": True,
                "return_code": 0,
                "stdout": (
                    "Install with npx skills add public/repo@wechat-official-account-helper\n\n"
                    "public/repo@wechat-official-account-helper\n"
                ),
                "stderr": "",
                "elapsed_ms": 10,
                "command": rendered,
            }

        if command[:3] == ["npx", "skills", "add"] and (
            "skills-ecosystem/wechat-official-account-helper" in command
        ):
            return {
                "success": False,
                "return_code": 1,
                "stdout": "",
                "stderr": (
                    "Authentication failed for "
                    "https://github.com/skills-ecosystem/wechat-official-account-helper.git."
                ),
                "elapsed_ms": 10,
                "command": rendered,
            }

        if command[:3] == ["npx", "skills", "add"] and (
            "public/repo@wechat-official-account-helper" in command
        ):
            skill_dir = Path(env["CODEX_HOME"]) / "skills" / "wechat-official-account-helper"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: wechat-official-account-helper\ndescription: 公开技能\n---\n",
                encoding="utf-8",
            )
            return {
                "success": True,
                "return_code": 0,
                "stdout": "installed",
                "stderr": "",
                "elapsed_ms": 10,
                "command": rendered,
            }

        raise AssertionError(f"未预期的命令: {command}")

    monkeypatch.setattr(service, "_run_command", fake_run_command)

    result = await service.install(
        package="npx skills add skills-ecosystem/wechat-official-account-helper",
        overwrite=False,
    )

    target_dir = workspace_dir / "wechat-official-account-helper"
    assert result["success"] is True
    assert result["recovered_by_find"] is True
    assert result["original_package_ref"] == "skills-ecosystem/wechat-official-account-helper"
    assert result["resolved_package_ref"] == "public/repo@wechat-official-account-helper"
    assert "wechat-official-account-helper" in result["skill_name"]
    assert target_dir.exists()
    assert (target_dir / "SKILL.md").exists()


@pytest.mark.asyncio
async def test_install_should_route_skillhub_package_to_workspace(tmp_path, monkeypatch):
    """`skillhub/<slug>` 应走 skillhub CLI，并通过 --dir 落到工作区。"""
    workspace_dir = tmp_path / "skills_md"
    service = SkillInstallerService(workspace_dir=workspace_dir)
    captured = {}

    async def fake_run_command(command, env, cwd, timeout_seconds):
        captured["command"] = command
        captured["cwd"] = cwd
        skill_dir = workspace_dir / "browser-use"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: browser-use\ndescription: 浏览器自动化\n---\n",
            encoding="utf-8",
        )
        return {
            "success": True,
            "return_code": 0,
            "stdout": "installed",
            "stderr": "",
            "elapsed_ms": 10,
            "command": " ".join(command),
        }

    monkeypatch.setattr(service, "_run_command", fake_run_command)

    result = await service.install(package="skillhub/browser-use", overwrite=False)

    assert result["success"] is True
    assert result["resolved_package_ref"] == "skillhub/browser-use"
    assert result["installed_path"] == str(workspace_dir / "browser-use")
    assert captured["command"][:4] == ["skillhub", "--dir", str(workspace_dir), "install"]
    assert captured["command"][4] == "browser-use"


@pytest.mark.asyncio
async def test_install_should_treat_skillhub_target_exists_as_success(tmp_path, monkeypatch):
    """SkillHub 返回 Target exists 且目录有效时，应按幂等成功处理。"""
    workspace_dir = tmp_path / "skills_md"
    service = SkillInstallerService(workspace_dir=workspace_dir)

    async def fake_run_command(command, env, cwd, timeout_seconds):
        skill_dir = workspace_dir / "browser-use"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: browser-use\ndescription: 浏览器自动化\n---\n",
            encoding="utf-8",
        )
        return {
            "success": False,
            "return_code": 1,
            "stdout": "",
            "stderr": f"Error: Target exists: {skill_dir}",
            "elapsed_ms": 10,
            "command": " ".join(command),
        }

    monkeypatch.setattr(service, "_run_command", fake_run_command)

    result = await service.install(package="skillhub/browser-use", overwrite=False)

    assert result["success"] is True
    assert result["skipped"] is True
    assert result["skill_file"] == str(workspace_dir / "browser-use" / "SKILL.md")
