#!/usr/bin/env python3
"""
根据用户描述创建技能骨架（适配本项目动态加载规范）
================================================

职责：
1. 在 app/skills/skills_md 下创建新技能目录
2. 生成符合规范的 SKILL.md
3. 可选生成 scripts/example_task.py 与 resources/param_schemas.json

说明：
- 不依赖第三方库，便于在受限环境执行
- 输出 JSON 摘要，方便上层 LLM 读取并反馈给用户
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path


def _split_csv(raw: str) -> list[str]:
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _normalize_value(raw: str) -> str:
    """
    将未被模板替换的占位符（如 {skill_name}）视为“未提供”，避免污染实际结果。
    """
    text = (raw or "").strip()
    if re.fullmatch(r"\{[a-zA-Z0-9_]+\}", text):
        return ""
    return text


def _slugify(name: str) -> str:
    """
    统一技能名规范：小写、数字、连字符，长度 <= 64。
    """
    text = (name or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    if not text:
        # 中文描述无法直接 slug 时，回退时间戳命名，避免失败中断
        text = f"skill-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}"
    return text[:64].strip("-")


def _short_desc_from_brief(brief: str) -> str:
    """
    生成 frontmatter description，保持短句且避免复杂符号导致解析歧义。
    """
    cleaned = re.sub(r"\s+", " ", brief).strip()
    cleaned = cleaned.replace('"', "'").replace(":", "：")
    if len(cleaned) > 70:
        cleaned = cleaned[:70] + "..."
    return f"根据用户描述执行“{cleaned}”相关任务。"


def _build_skill_md(
    *,
    skill_name: str,
    brief: str,
    required_tools: list[str],
    optional_tools: list[str],
    tags: list[str],
    include_script_template: bool,
    include_param_schema: bool,
) -> str:
    scripts_section = "- scripts/example_task.py" if include_script_template else "- 无"
    resources_rows: list[str] = []
    if include_param_schema:
        resources_rows.append("- resources/param_schemas.json")
    resources_rows.append("- resources/skill_notes.md")
    resources_section = "\n".join(resources_rows)

    # 使用 JSON 数组格式，兼容当前 SkillManager 的 frontmatter 简化解析器
    required_tools_json = json.dumps(required_tools, ensure_ascii=False)
    optional_tools_json = json.dumps(optional_tools, ensure_ascii=False)
    tags_json = json.dumps(tags, ensure_ascii=False)

    return f"""---
name: {skill_name}
description: {_short_desc_from_brief(brief)}
required_tools: {required_tools_json}
optional_tools: {optional_tools_json}
tags: {tags_json}
memory_include_short_term: true
---

# 何时使用 (When to use)
- 当用户需求与以下场景一致时：{brief}
- 当任务需要复用此场景的固定流程而不是一次性临时回答时

# 输入参数 (Inputs)
- input: 用户给该技能的原始输入（必填）
- context: 业务上下文补充信息（可选）

# 执行指令 (Instructions)
你是“{skill_name}”技能执行助手，请遵循以下要求：
1. 先澄清输入是否完整，不完整时说明缺什么。
2. 优先使用可用工具获取真实结果，禁止编造。
3. 输出时分三段：结论、关键证据、下一步建议。
4. 若调用工具失败，给出失败原因与可执行修复建议。

技能目标说明：
{brief}

# 脚本 (Scripts)
{scripts_section}

# 资源 (Resources)
{resources_section}
"""


def _build_param_schema_json() -> dict[str, dict[str, object]]:
    return {
        "input": {
            "label": "输入内容",
            "description": "执行该技能所需的主要输入。",
            "examples": ["请处理这个任务", "用户给定的目标描述"],
            "required": True,
        },
        "context": {
            "label": "上下文信息",
            "description": "辅助该技能判断的业务背景、约束或历史信息。",
            "examples": ["优先使用 shell_exec", "输出要简洁"],
            "required": False,
        },
    }


def _build_example_script(skill_name: str) -> str:
    return f'''#!/usr/bin/env python3
"""
{skill_name} 示例脚本
--------------------
该脚本用于演示此技能如何封装可复用的确定性逻辑。
"""

from __future__ import annotations


def main() -> None:
    print("这是 {skill_name} 的示例脚本，请按真实需求替换逻辑。")


if __name__ == "__main__":
    main()
'''


def _build_skill_notes(brief: str) -> str:
    return f"""# 技能备注

本技能由 `skill-creator` 自动生成。

原始需求描述：
{brief}

建议下一步：
1. 补充更具体的 `何时使用` 场景。
2. 按真实工具调用链完善 `执行指令`。
3. 如需参数精细化，扩展 `resources/param_schemas.json`。
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="根据描述创建技能骨架")
    parser.add_argument("--brief", required=True, help="用户对目标技能的自然语言描述")
    parser.add_argument("--skill-name", default="", help="目标技能名（可选）")
    parser.add_argument(
        "--target-dir",
        default="app/skills/skills_md",
        help="技能根目录（默认 app/skills/skills_md）",
    )
    parser.add_argument("--required-tools", default="", help="必需工具，逗号分隔")
    parser.add_argument("--optional-tools", default="", help="可选工具，逗号分隔")
    parser.add_argument("--tags", default="", help="标签，逗号分隔")
    parser.add_argument(
        "--include-script-template",
        choices=["yes", "no"],
        default="yes",
        help="是否生成示例脚本",
    )
    parser.add_argument(
        "--include-param-schema",
        choices=["yes", "no"],
        default="yes",
        help="是否生成 resources/param_schemas.json",
    )
    parser.add_argument(
        "--overwrite",
        choices=["yes", "no"],
        default="no",
        help="已存在时是否覆盖",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    brief = _normalize_value(args.brief)
    if not brief:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "brief 不能为空，请提供技能需求描述",
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    skill_name = _slugify(_normalize_value(args.skill_name) or brief)
    target_dir = Path(_normalize_value(args.target_dir) or "app/skills/skills_md").expanduser().resolve()
    skill_dir = target_dir / skill_name
    overwrite = _normalize_value(args.overwrite) == "yes"

    required_tools = _split_csv(_normalize_value(args.required_tools)) or ["shell_exec", "file_read"]
    optional_tools = _split_csv(_normalize_value(args.optional_tools)) or ["list_dir"]
    tags = _split_csv(_normalize_value(args.tags)) or ["auto-generated", "skill"]

    if skill_dir.exists() and not overwrite:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "技能目录已存在，且未开启覆盖模式",
                    "skill_name": skill_name,
                    "skill_dir": str(skill_dir),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    # 覆盖模式：保留目录，直接覆盖关键文件
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (skill_dir / "resources").mkdir(parents=True, exist_ok=True)

    created_files: list[str] = []

    skill_md_path = skill_dir / "SKILL.md"
    skill_md_path.write_text(
        _build_skill_md(
            skill_name=skill_name,
            brief=brief,
            required_tools=required_tools,
            optional_tools=optional_tools,
            tags=tags,
            include_script_template=_normalize_value(args.include_script_template or "yes") != "no",
            include_param_schema=_normalize_value(args.include_param_schema or "yes") != "no",
        ),
        encoding="utf-8",
    )
    created_files.append(str(skill_md_path))

    notes_path = skill_dir / "resources" / "skill_notes.md"
    notes_path.write_text(_build_skill_notes(brief), encoding="utf-8")
    created_files.append(str(notes_path))

    if _normalize_value(args.include_param_schema or "yes") != "no":
        param_schema_path = skill_dir / "resources" / "param_schemas.json"
        param_schema_path.write_text(
            json.dumps(_build_param_schema_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        created_files.append(str(param_schema_path))

    if _normalize_value(args.include_script_template or "yes") != "no":
        example_script_path = skill_dir / "scripts" / "example_task.py"
        example_script_path.write_text(_build_example_script(skill_name), encoding="utf-8")
        example_script_path.chmod(0o755)
        created_files.append(str(example_script_path))

    payload = {
        "ok": True,
        "skill_name": skill_name,
        "skill_dir": str(skill_dir),
        "created_files": created_files,
        "overwrite": overwrite,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
