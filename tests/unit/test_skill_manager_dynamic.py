import json

import pytest

from app.skills.manager import SkillManager


def _write_demo_skill(tmp_path, skill_name: str = "demo_skill"):
    skill_dir = tmp_path / skill_name
    resource_dir = skill_dir / "resources"
    resource_dir.mkdir(parents=True, exist_ok=True)

    (resource_dir / "param_schemas.json").write_text(
        json.dumps(
            {
                "input_text": {
                    "label": "输入文本",
                    "description": "用于演示的输入文本",
                    "examples": ["你好，世界"],
                    "required": True,
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {skill_name}
description: 用于测试动态加载能力。
---
# 何时使用 (When to use)
- 当需要验证技能发现和懒加载时

# 输入参数 (Inputs)
- input_text: 用于演示的输入文本

# 执行指令 (Instructions)
请处理以下输入文本：
{{input_text}}

# 脚本 (Scripts)
- 无

# 资源 (Resources)
- resources/param_schemas.json
""",
        encoding="utf-8",
    )
    return skill_dir


def test_discover_and_lazy_load_skill(tmp_path):
    _write_demo_skill(tmp_path)

    manager = SkillManager(skills_root=tmp_path, auto_discover=True)

    metadata = manager.list_skill_metadata()
    assert len(metadata) == 1
    assert metadata[0]["skill_id"] == "demo_skill"
    assert metadata[0]["name"] == "demo_skill"
    assert metadata[0]["inputs"] == ["input_text"]
    assert metadata[0]["input_descriptions"]["input_text"] == "用于演示的输入文本"

    # discover 之后尚未触发完整加载
    assert "demo_skill" not in manager._loaded_skills

    skill = manager.get_skill("demo_skill")
    assert skill is not None
    assert skill.skill_id == "demo_skill"
    assert "{input_text}" in skill.prompt_template
    assert "input_text" in skill.param_schemas
    assert skill.param_schemas["input_text"].label == "输入文本"


def test_frontmatter_yaml_should_parse_structured_runtime_dependencies(tmp_path):
    skill_dir = tmp_path / "yaml_skill"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "run_demo.js").write_text("console.log('ok')\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        """---
name: yaml_skill
description: 使用多行 YAML frontmatter 的技能。
runtime_dependencies:
  - type: npm
    packages: ["cheerio"]
    working_dir: "."
    timeout_seconds: 120
output_validators:
  - type: must_contain_any
    markers: ["结果", "文章"]
    error: 必须包含结果字段
---
# 何时使用 (When to use)
- 当需要测试 frontmatter 多行 YAML 解析时

# 执行指令 (Instructions)
请执行 scripts/run_demo.js

# 脚本 (Scripts)
- scripts/run_demo.js
""",
        encoding="utf-8",
    )

    manager = SkillManager(skills_root=tmp_path, auto_discover=True)
    meta = manager.list_skill_metadata()[0]
    skill = manager.get_skill("yaml_skill")

    assert meta["skill_id"] == "yaml_skill"
    # 兼容外部下载技能：未显式声明工具时，不应被框架偷偷写成项目私有规范
    assert meta["required_tools"] == []
    assert skill is not None
    assert len(skill.runtime_dependencies) == 1
    assert skill.runtime_dependencies[0].type == "npm"
    assert skill.runtime_dependencies[0].packages == ["cheerio"]
    assert len(skill.output_validators) == 1
    assert skill.output_validators[0]["type"] == "must_contain_any"


def test_should_parse_parameter_alias_and_infer_scripts_from_body(tmp_path):
    skill_dir = tmp_path / "wechat_like_skill"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "search_wechat.js").write_text("console.log('ok')\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        """---
name: wechat_like_skill
description: 模拟未严格按标准章节编写的外部技能。
---
# 适用场景
- 搜索公众号文章

## 参数说明
- query：搜索关键词

## 工作流程
```bash
node scripts/search_wechat.js "关键词" -n 1
```
""",
        encoding="utf-8",
    )

    manager = SkillManager(skills_root=tmp_path, auto_discover=True)
    meta = manager.list_skill_metadata()[0]
    skill = manager.get_skill("wechat_like_skill")

    assert meta["inputs"] == ["query"]
    assert meta["input_descriptions"]["query"] == "搜索关键词"
    assert meta["scripts"] == ["scripts/search_wechat.js"]
    assert skill is not None
    assert "query" in skill.param_schemas


@pytest.mark.asyncio
async def test_execute_skill_runtime(tmp_path):
    _write_demo_skill(tmp_path)
    manager = SkillManager(skills_root=tmp_path, auto_discover=True)

    class FakeResponse:
        def __init__(self):
            self.content = "执行成功"
            self.usage = {"total_tokens": 1}

    class FakeLLM:
        def __init__(self):
            self.last_messages = None
            self.last_config = None

        async def infer(self, messages, config):
            self.last_messages = messages
            self.last_config = config
            return FakeResponse()

    class DummyConfig:
        tools = []

    llm = FakeLLM()
    result = await manager.execute_skill_runtime(
        skill_name="demo_skill",
        user_request="请处理一段测试文本",
        inputs={"input_text": "hello"},
        llm_hub=llm,
        config=DummyConfig(),
    )

    assert result.content == "执行成功"
    assert llm.last_messages is not None
    assert "你正在执行技能：demo_skill" in llm.last_messages[0]["content"]
    assert "hello" in llm.last_messages[0]["content"]


def test_auto_reload_on_skill_added(tmp_path):
    _write_demo_skill(tmp_path, "demo_skill")
    manager = SkillManager(skills_root=tmp_path, auto_discover=True)

    initial_ids = {item["skill_id"] for item in manager.list_skill_metadata()}
    assert initial_ids == {"demo_skill"}

    # 新增技能目录后，不手动 reload，调用 list_skill_metadata 应自动检测变化并重载
    _write_demo_skill(tmp_path, "new_skill")
    updated_ids = {item["skill_id"] for item in manager.list_skill_metadata()}
    assert updated_ids == {"demo_skill", "new_skill"}


def test_auto_reload_on_skill_deleted(tmp_path):
    _write_demo_skill(tmp_path, "demo_skill")
    removed_dir = _write_demo_skill(tmp_path, "to_be_deleted")
    manager = SkillManager(skills_root=tmp_path, auto_discover=True)

    initial_ids = {item["skill_id"] for item in manager.list_skill_metadata()}
    assert initial_ids == {"demo_skill", "to_be_deleted"}

    # 删除技能目录后，不手动 reload，调用 list_skill_metadata 应自动剔除
    for p in sorted(removed_dir.rglob("*"), reverse=True):
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            p.rmdir()
    removed_dir.rmdir()

    updated_ids = {item["skill_id"] for item in manager.list_skill_metadata()}
    assert updated_ids == {"demo_skill"}
