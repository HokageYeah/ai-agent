"""
执行引擎敏感工具必需声明测试
===========================

验证场景：
- 技能在 required_tools 中声明了 file_write（敏感工具）
- 执行引擎会在技能内部过滤敏感工具
- 不应因此误报“required_tools 缺失”并导致技能直接失败
"""

from types import SimpleNamespace

import pytest

from app.agents.base import Agent
from app.agents.execution import ExecutionEngine
from app.agents.planning import Plan, PlanStep
from app.skills.base import Skill
from app.tools.hub import ToolHub


class DummySkillManager:
    """最小技能管理器桩，仅提供 get_skill 接口。"""

    def __init__(self, skill: Skill):
        self._skill = skill

    def get_skill(self, skill_id: str):
        if skill_id == self._skill.skill_id:
            return self._skill
        return None


class DummyLLMHub:
    """最小 LLMHub 桩，返回固定文本，避免依赖外部模型。"""

    def __init__(self, content: str = "技能执行成功（测试桩返回）"):
        self.calls = 0
        self.content = content
        self.tools_history = []

    async def infer(self, messages, config):
        self.calls += 1
        self.tools_history.append(list(getattr(config, "tools", []) or []))
        return SimpleNamespace(content=self.content)


@pytest.mark.asyncio
async def test_sensitive_required_tool_should_not_be_false_missing():
    """required_tools 仅包含敏感工具时，不应误报缺失导致失败。"""
    tool_hub = ToolHub()
    skill = Skill(
        skill_id="sensitive_required_skill",
        name="Sensitive Required Skill",
        description="测试敏感工具必需声明",
        prompt_template="请执行任务：{task}",
        required_tools=["file_write"],
        optional_tools=[],
    )
    skill_manager = DummySkillManager(skill=skill)
    llm_hub = DummyLLMHub()
    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        llm_hub=llm_hub,
    )

    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role",
    )
    plan = Plan(
        steps=[
            PlanStep(
                action="skill",
                skill_id="sensitive_required_skill",
                params={"task": "验证敏感工具声明不误报"},
            ),
            PlanStep(action="final_answer", content="技能执行完成"),
        ]
    )

    result = await execution_engine.execute_plan(agent, plan)

    assert result.success is True
    assert result.step_results[0]["action"] == "skill"
    assert result.step_results[0]["success"] is True
    assert "required_tools 未在当前运行时工具集中满足" not in str(
        result.step_results[0].get("error", "")
    )


@pytest.mark.asyncio
async def test_skill_creator_should_be_blocked_without_explicit_intent():
    """未明确要求创建技能时，必须拦截 skill-creator 调用。"""
    tool_hub = ToolHub()
    skill = Skill(
        skill_id="skill-creator",
        name="Skill Creator",
        description="创建技能能力包",
        prompt_template="请根据 brief 执行：{brief}",
        required_tools=[],
        optional_tools=[],
    )
    skill_manager = DummySkillManager(skill=skill)
    llm_hub = DummyLLMHub()
    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        llm_hub=llm_hub,
    )
    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role",
    )
    plan = Plan(
        steps=[
            PlanStep(
                action="skill",
                skill_id="skill-creator",
                params={"brief": "基于订单数据创建一份 Markdown 报告"},
            ),
            PlanStep(action="final_answer", content="完成"),
        ]
    )

    result = await execution_engine.execute_plan(
        agent,
        plan,
        context={"task": "查询订单1002并写成 md 文档"},
    )

    assert result.step_results[0]["action"] == "skill"
    assert result.step_results[0]["success"] is False
    assert "仅在用户明确要求" in str(result.step_results[0]["error"])
    assert llm_hub.calls == 0


@pytest.mark.asyncio
async def test_skill_creator_should_pass_with_explicit_intent():
    """明确要求创建技能时，允许执行 skill-creator。"""
    tool_hub = ToolHub()
    skill = Skill(
        skill_id="skill-creator",
        name="Skill Creator",
        description="创建技能能力包",
        prompt_template="请根据 brief 执行：{brief}",
        required_tools=[],
        optional_tools=[],
    )
    skill_manager = DummySkillManager(skill=skill)
    llm_hub = DummyLLMHub()
    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        llm_hub=llm_hub,
    )
    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role",
    )
    plan = Plan(
        steps=[
            PlanStep(
                action="skill",
                skill_id="skill-creator",
                params={"brief": "创建一个订单报告技能"},
            ),
            PlanStep(action="final_answer", content="完成"),
        ]
    )

    result = await execution_engine.execute_plan(
        agent,
        plan,
        context={"task": "请创建一个订单报告技能，用于自动生成 md 文档"},
    )

    assert result.step_results[0]["action"] == "skill"
    assert result.step_results[0]["success"] is True
    # 说明：执行引擎在 final_answer 阶段可能触发一次答案合成推理，因此这里断言至少被调用一次。
    assert llm_hub.calls >= 1


@pytest.mark.asyncio
async def test_skill_without_declared_tools_should_disable_internal_tools():
    """技能未声明 required/optional 工具时，应默认禁用技能内部工具。"""
    tool_hub = ToolHub()
    # 直接伪造工具 Schema 列表，模拟 Agent 拥有多种可用工具。
    tool_hub.get_schemas = lambda: [
        {"name": "file_read", "description": "read file", "parameters": {"type": "object"}},
        {"name": "list_dir", "description": "list dir", "parameters": {"type": "object"}},
        {"name": "shell_exec", "description": "exec shell", "parameters": {"type": "object"}},
    ]
    skill = Skill(
        skill_id="no_tool_skill",
        name="No Tool Skill",
        description="未声明工具的技能",
        prompt_template="请输出 Markdown 正文：{topic}",
        required_tools=[],
        optional_tools=[],
    )
    skill_manager = DummySkillManager(skill=skill)
    llm_hub = DummyLLMHub(content="# 标题\n\n正文内容")
    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        llm_hub=llm_hub,
    )
    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role",
        available_tools=["file_read", "list_dir", "shell_exec"],
    )
    plan = Plan(
        steps=[
            PlanStep(
                action="skill",
                skill_id="no_tool_skill",
                params={"topic": "订单详情文档"},
            ),
        ]
    )

    result = await execution_engine.execute_plan(agent, plan)

    assert result.success is True
    assert result.step_results[0]["success"] is True
    assert llm_hub.tools_history, "应记录至少一次技能推理调用"
    assert llm_hub.tools_history[0] == []


def test_skill_output_validation_should_reject_process_report_style():
    """通用技能返回“流程汇报口吻”时必须判定无效。"""
    tool_hub = ToolHub()
    skill = Skill(
        skill_id="dummy",
        name="Dummy Skill",
        description="dummy",
        prompt_template="{task}",
    )
    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=DummySkillManager(skill=skill),
        llm_hub=DummyLLMHub(),
    )

    ok, reason = execution_engine._validate_skill_output(
        skill_id="generic_skill",
        output_text=(
            "任务已完成！我已经成功执行以下步骤：\n"
            "1. **生成文档**：已完成内容生成\n"
            "2. **保存文件**：已保存到桌面"
        ),
        params={},
    )

    assert ok is False
    assert "执行过程说明" in reason


def test_skill_output_validation_should_accept_plain_result():
    """通用技能返回结果正文时应通过校验。"""
    tool_hub = ToolHub()
    skill = Skill(
        skill_id="dummy",
        name="Dummy Skill",
        description="dummy",
        prompt_template="{task}",
    )
    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=DummySkillManager(skill=skill),
        llm_hub=DummyLLMHub(),
    )

    ok, reason = execution_engine._validate_skill_output(
        skill_id="generic_skill",
        output_text="# 订单号1002详情\n\n## 客户信息\n- 姓名：张三",
        params={},
    )

    assert ok is True
    assert reason == ""


# ========== 声明式 output_validators 校验测试 ==========


def test_output_validators_must_contain_any_rejects():
    """声明式 must_contain_any 规则：输出不含任何标记词时应判定失败。"""
    tool_hub = ToolHub()
    skill = Skill(
        skill_id="weather",
        name="Weather",
        description="天气查询",
        prompt_template="{task}",
        output_validators=[
            {
                "type": "must_contain_any",
                "markers": ["°C", "温度", "湿度", "天气"],
                "error": "weather 技能未返回可识别的天气事实字段",
            }
        ],
    )
    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=DummySkillManager(skill=skill),
        llm_hub=DummyLLMHub(),
    )

    # 输出中不含任何天气标记词 → 应被拒绝
    # NOTE: 测试文本刻意避开所有 markers（°C / 温度 / 湿度 / 天气），确保校验必定拦截
    ok, reason = execution_engine._validate_skill_output(
        skill_id="weather",
        output_text="这是一段完全无关的文本，只有一些普通数据。",
        params={},
        validators=skill.output_validators,
    )
    assert ok is False
    assert "天气事实字段" in reason


def test_output_validators_must_not_contain_any_rejects():
    """声明式 must_not_contain_any 规则：输出含引导话术时应判定失败。"""
    tool_hub = ToolHub()
    skill = Skill(
        skill_id="weather",
        name="Weather",
        description="天气查询",
        prompt_template="{task}",
        output_validators=[
            {
                "type": "must_contain_any",
                "markers": ["°C", "温度", "湿度", "天气"],
                "error": "weather 技能未返回可识别的天气事实字段",
            },
            {
                "type": "must_not_contain_any",
                "markers": ["请告诉我您要查询的城市", "您可以直接说例如"],
                "error": "weather 技能返回引导话术，未直接给出查询结果",
            },
        ],
    )
    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=DummySkillManager(skill=skill),
        llm_hub=DummyLLMHub(),
    )

    # 输出含天气关键词但同时含引导话术 → 应被第二条规则拒绝
    ok, reason = execution_engine._validate_skill_output(
        skill_id="weather",
        output_text="当前天气晴朗。请告诉我您要查询的城市，我可以提供更详细的信息。",
        params={},
        validators=skill.output_validators,
    )
    assert ok is False
    assert "引导话术" in reason


def test_output_validators_pass_when_valid():
    """声明式校验：输出满足所有声明式规则时应通过。"""
    tool_hub = ToolHub()
    skill = Skill(
        skill_id="weather",
        name="Weather",
        description="天气查询",
        prompt_template="{task}",
        output_validators=[
            {
                "type": "must_contain_any",
                "markers": ["°C", "温度", "湿度", "天气"],
                "error": "weather 技能未返回可识别的天气事实字段",
            },
            {
                "type": "must_not_contain_any",
                "markers": ["请告诉我您要查询的城市", "您可以直接说例如"],
                "error": "weather 技能返回引导话术，未直接给出查询结果",
            },
        ],
    )
    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=DummySkillManager(skill=skill),
        llm_hub=DummyLLMHub(),
    )

    # 输出含天气事实且无引导话术 → 应通过所有校验
    ok, reason = execution_engine._validate_skill_output(
        skill_id="weather",
        output_text="北京今日天气：晴，温度 25°C，湿度 45%，东风 3 级。",
        params={"location": "北京"},
        validators=skill.output_validators,
    )
    assert ok is True
    assert reason == ""
