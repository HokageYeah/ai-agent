"""
测试 LangGraph Agent Executor
==================

测试基于 LangGraph 的 Agent 执行器
"""

import pytest
from types import SimpleNamespace
from app.agents.langgraph_executor import LangGraphAgentExecutor, AgentState
from app.agents.base import Agent
from app.agents.planning import Plan, PlanStep
from app.agents.execution import ExecutionResult
from app.core.llm_mock import MockLLM
from app.llm_hub.inference import InferenceEngine
from app.llm_hub.registry import ModelRegistry
from app.memory.agent_run_memory import AgentRunMemory
from app.tools.hub import ToolHub
from app.skills.manager import SkillManager


def _build_executor() -> LangGraphAgentExecutor:
    """
    构建用于单元测试的执行器实例。

    说明：
    - 统一初始化逻辑，避免每个测试重复样板代码。
    - 使用 MockLLM，确保测试不依赖外部模型服务。
    """
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    tool_hub = ToolHub()
    skill_manager = SkillManager()
    return LangGraphAgentExecutor(
        llm_hub=inference_engine,
        tool_hub=tool_hub,
        skill_manager=skill_manager
    )


@pytest.mark.asyncio
async def test_langgraph_executor_initialization():
    """测试 LangGraph Executor 初始化"""
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    tool_hub = ToolHub()
    skill_manager = SkillManager()
    
    executor = LangGraphAgentExecutor(
        llm_hub=inference_engine,
        tool_hub=tool_hub,
        skill_manager=skill_manager
    )
    
    assert executor is not None
    assert executor.graph is not None
    assert executor.planning_engine is not None
    assert executor.execution_engine is not None
    assert executor.reflection_engine is not None


@pytest.mark.asyncio
async def test_agent_state_structure():
    """测试 AgentState 结构"""
    state: AgentState = {
        "messages": [],
        "current_plan": None,
        "tool_outputs": [],
        "iterations": 0,
        "final_result": None,
        "task": "测试任务",
        "agent": None
    }
    
    assert "messages" in state
    assert "current_plan" in state
    assert "tool_outputs" in state
    assert "iterations" in state
    assert "final_result" in state


@pytest.mark.asyncio
async def test_execute_simple_task():
    """测试执行简单任务"""
    # 创建 Mock LLM
    mock_llm = MockLLM()
    
    # 设置规划响应
    mock_llm.default_response = """```json
{
  "steps": [
    {"action": "final_answer", "content": "任务完成"}
  ],
  "reasoning": "直接返回结果"
}
```"""
    
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    tool_hub = ToolHub()
    skill_manager = SkillManager()
    
    executor = LangGraphAgentExecutor(
        llm_hub=inference_engine,
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        max_iterations=3
    )
    
    # 创建测试 Agent
    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role"
    )
    
    # 执行任务
    result = await executor.execute(
        agent=agent,
        task="测试任务"
    )
    
    assert result is not None
    assert "success" in result


@pytest.mark.asyncio
async def test_max_iterations():
    """测试最大迭代次数限制"""
    mock_llm = MockLLM()
    
    # 设置一个永远需要重新规划的响应
    mock_llm.responses = {
        "default": """```json
{
  "steps": [{"action": "final_answer", "content": "测试"}],
  "reasoning": "测试"
}
```""",
        "reflect": """```json
{
  "success": false,
  "needs_replanning": true,
  "feedback": "需要重新规划",
  "summary": "未完成"
}
```"""
    }
    
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    tool_hub = ToolHub()
    skill_manager = SkillManager()
    
    executor = LangGraphAgentExecutor(
        llm_hub=inference_engine,
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        max_iterations=2  # 设置较小的最大迭代次数
    )
    
    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role"
    )
    
    result = await executor.execute(
        agent=agent,
        task="测试任务"
    )
    
    # 应该在达到最大迭代次数后停止
    assert result is not None
    assert result["iterations"] <= 2


@pytest.mark.asyncio
async def test_execute_node_should_pass_run_memory_and_iteration_to_execution_context(monkeypatch):
    """测试 _execute_node 会把 run_memory 和 iteration 透传给执行引擎上下文"""
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    tool_hub = ToolHub()
    skill_manager = SkillManager()

    executor = LangGraphAgentExecutor(
        llm_hub=inference_engine,
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        max_iterations=3
    )

    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role"
    )
    plan = Plan(steps=[PlanStep("final_answer", content="任务完成")], reasoning="测试")
    run_memory = AgentRunMemory(task="测试任务", agent_id=agent.agent_id, agent_name=agent.name)
    captured: dict = {}

    async def fake_execute_plan(*args, **kwargs):
        captured["context"] = kwargs.get("context")
        return ExecutionResult(success=True, result="ok", step_results=[])

    monkeypatch.setattr(executor.execution_engine, "execute_plan", fake_execute_plan)

    state: AgentState = {
        "messages": [],
        "current_plan": plan,
        "tool_outputs": [],
        "iterations": 2,
        "final_result": None,
        "task": "测试任务",
        "agent": agent,
        "error_context": [],
        "error_analysis": None,
        "reflection_history": [],
        "pending_confirmations": {},
        "pending_user_inputs": {},
        "user_rejected_tools": [],
        "run_memory": run_memory,
    }

    await executor._execute_node(state, stream_callback=None)

    assert "context" in captured
    assert captured["context"]["run_memory"] is run_memory
    assert captured["context"]["iteration"] == 2


@pytest.mark.asyncio
async def test_execute_node_handles_none_error_in_failed_step(monkeypatch):
    """测试失败步骤 error=None 时不会触发 NoneType 下标异常"""
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    tool_hub = ToolHub()
    skill_manager = SkillManager()

    executor = LangGraphAgentExecutor(
        llm_hub=inference_engine,
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        max_iterations=3
    )

    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role"
    )
    plan = Plan(
        steps=[PlanStep("delegate", agent_id="general_agent", task="测试委派失败")],
        reasoning="测试 error=None 的失败路径"
    )
    run_memory = AgentRunMemory(task="测试任务", agent_id=agent.agent_id, agent_name=agent.name)
    events = []

    async def fake_execute_plan(*args, **kwargs):
        on_step_complete = kwargs.get("on_step_complete")
        failed_step_result = {
            "success": False,
            "action": "delegate",
            "agent_id": "general_agent",
            "result": None,
            "error": None
        }
        if on_step_complete is not None:
            await on_step_complete(failed_step_result, 1, 1)
        return ExecutionResult(
            success=False,
            result=None,
            step_results=[failed_step_result],
            error=None
        )

    async def stream_callback(event):
        events.append(event)

    monkeypatch.setattr(executor.execution_engine, "execute_plan", fake_execute_plan)

    state: AgentState = {
        "messages": [],
        "current_plan": plan,
        "tool_outputs": [],
        "iterations": 1,
        "final_result": None,
        "task": "测试任务",
        "agent": agent,
        "error_context": [],
        "error_analysis": None,
        "reflection_history": [],
        "pending_confirmations": {},
        "pending_user_inputs": {},
        "user_rejected_tools": [],
        "run_memory": run_memory,
    }

    new_state = await executor._execute_node(state, stream_callback=stream_callback)

    # 应该成功进入错误收集，不应因 error=None 崩溃
    assert new_state["error_context"]
    assert new_state["error_context"][0]["error_msg"] == "Unknown error"

    # 步骤失败事件中的 error 字段应被归一化为字符串
    step_error_events = [
        e for e in events
        if e.get("event") == "agent_message"
        and (e.get("data") or {}).get("progress", {}).get("stage") == "step_error"
    ]
    assert step_error_events
    assert step_error_events[0]["data"].get("error") == "Unknown error"


@pytest.mark.parametrize(
    "task, expected",
    [
        ("列出你所有可用的技能", True),
        ("你有哪些skill", True),
        ("list all available skills", True),
        ("what skills do you have", True),
        ("请先检查是否已安装 SkillHub 商店，若未安装请安装 find-skills 技能", False),
        ("请创建一个新的天气技能", False),
        ("帮我生成一个 skill 模板", False),
        ("把这段话翻译成英文", False),
    ],
)
def test_is_skill_inventory_query(task: str, expected: bool):
    """测试技能清单查询意图识别，避免误判到“创建技能”请求。"""
    executor = _build_executor()
    assert executor._is_skill_inventory_query(task) is expected


def test_resolve_available_skills_inventory_query_should_return_gated_all_and_skip_routing(monkeypatch):
    """
    测试技能清单查询时应直接返回“门禁后的全量技能”，不应走 Top-K 路由裁剪。

    设计目的：
    - 防止“列技能”类问题被动态路由压缩上下文，导致模型误答“只有一个技能”。
    - 同时确保受限技能（skill-creator/dynamic_probe）不会在普通盘点意图下暴露。
    """
    executor = _build_executor()
    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role",
    )
    fake_skills = [
        SimpleNamespace(skill_id="skill-creator", name="技能创建", description="创建技能包"),
        SimpleNamespace(skill_id="dynamic_probe", name="动态探针", description="探针"),
        SimpleNamespace(skill_id="translation", name="翻译", description="翻译文本"),
        SimpleNamespace(skill_id="weather", name="天气", description="查询天气"),
    ]
    monkeypatch.setattr(executor.skill_manager, "list_skills", lambda: fake_skills)
    route_called = {"value": False}

    def fake_route(**kwargs):
        route_called["value"] = True
        return [fake_skills[0]]

    monkeypatch.setattr(executor, "_route_skills_by_metadata", fake_route)

    selected = executor._resolve_available_skills(agent=agent, task="列出你所有可用的技能")
    selected_ids = [s.skill_id for s in selected]
    assert selected_ids == ["translation", "weather"]
    assert route_called["value"] is False


def test_resolve_available_skills_non_inventory_query_should_use_routing(monkeypatch):
    """测试非技能清单问题仍保持动态路由行为。"""
    executor = _build_executor()
    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role",
    )
    fake_skills = [
        SimpleNamespace(skill_id="dynamic_probe", name="动态探针", description="探针"),
        SimpleNamespace(skill_id="translation", name="翻译", description="翻译文本"),
    ]
    monkeypatch.setattr(executor.skill_manager, "list_skills", lambda: fake_skills)
    route_called = {"value": False}

    def fake_route(**kwargs):
        route_called["value"] = True
        return [fake_skills[1]]

    monkeypatch.setattr(executor, "_route_skills_by_metadata", fake_route)

    selected = executor._resolve_available_skills(agent=agent, task="把这句话翻译成英文")
    assert route_called["value"] is True
    assert selected == [fake_skills[1]]


def test_resolve_available_skills_install_task_should_not_be_treated_as_inventory(monkeypatch):
    """安装任务不应命中“技能清单查询”分支，且应在路由前隐藏受限技能。"""
    executor = _build_executor()
    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role",
    )
    fake_skills = [
        SimpleNamespace(skill_id="skill-creator", name="技能创建", description="创建技能包"),
        SimpleNamespace(skill_id="text_writing", name="写作", description="写作"),
    ]
    monkeypatch.setattr(executor.skill_manager, "list_skills", lambda: fake_skills)
    route_called = {"value": False}
    captured = {}

    def fake_route(**kwargs):
        route_called["value"] = True
        captured["all_skills"] = kwargs.get("all_skills", [])
        return kwargs.get("all_skills", [])

    monkeypatch.setattr(executor, "_route_skills_by_metadata", fake_route)

    selected = executor._resolve_available_skills(
        agent=agent,
        task="请先检查是否已安装 SkillHub，若未安装就安装，再安装 find-skills 技能",
    )
    selected_ids = [s.skill_id for s in selected]
    routed_ids = [s.skill_id for s in captured.get("all_skills", [])]

    assert route_called["value"] is True
    assert "skill-creator" not in routed_ids
    assert selected_ids == ["text_writing"]


@pytest.mark.parametrize(
    "task, expected",
    [
        ("请创建一个新的订单分析技能", True),
        ("帮我修改 weather 技能的输入参数", True),
        ("use skill-creator to scaffold a new skill", True),
        ("使用写作技能创建一份订单报告", False),
        ("帮我写一封邮件", False),
    ],
)
def test_is_explicit_skill_creator_request(task: str, expected: bool):
    """测试 skill-creator 显式触发判定，避免“写作技能创建文档”误判。"""
    executor = _build_executor()
    assert executor._is_explicit_skill_creator_request(task) is expected


@pytest.mark.parametrize(
    "task, expected",
    [
        ("npx skills add demo/repo@wechat-article-search -g -y，运行这个命令", True),
        ("请执行 bash ./deploy.sh", True),
        ("帮我把这句话翻译成英文", False),
        ("请安装一个微信公众号搜索技能", False),
    ],
)
def test_is_explicit_system_command_task(task: str, expected: bool):
    """测试显式系统命令任务识别，避免普通自然语言任务被误判为命令执行。"""
    executor = _build_executor()
    assert executor._is_explicit_system_command_task(task) is expected


@pytest.mark.parametrize(
    "task, expected",
    [
        ("请安装 wechat-article-search 技能", True),
        ("npx skills add demo/repo@wechat-article-search -g -y", True),
        ("帮我列出可用技能", False),
        ("请执行 bash ./deploy.sh", False),
    ],
)
def test_is_skill_install_request(task: str, expected: bool):
    """测试技能安装任务识别，兼容自然语言和命令式写法。"""
    executor = _build_executor()
    assert executor._is_skill_install_request(task) is expected


def test_build_capability_gap_delegate_plan_should_delegate_command_task_to_general_agent():
    """
    测试：协调型 Agent 遇到显式命令执行任务、且自身无 shell_exec/skill_install 时，
    应直接委派给 general_agent，而不是回答“做不到”。
    """
    executor = _build_executor()
    agent = Agent(
        agent_id="cs_master",
        name="客服总监",
        description="协调型 Agent",
        role="负责委派",
        available_tools=["datetime", "spawn_agent", "send_message"],
        child_agents=["general_agent"],
    )
    available_tools = [
        SimpleNamespace(name="datetime"),
        SimpleNamespace(name="spawn_agent"),
        SimpleNamespace(name="send_message"),
    ]

    plan = executor._build_capability_gap_delegate_plan(
        agent=agent,
        task="npx skills add wuchubuzai2018/expert-skills-hub@wechat-article-search -g -y 运行这个命令，安装这个技能",
        available_tools=available_tools,
    )

    assert plan is not None
    assert len(plan.steps) == 2
    assert plan.steps[0].action == "delegate"
    assert plan.steps[0].params["agent_id"] == "general_agent"
    assert "wechat-article-search" in plan.steps[0].params["task"]
    assert plan.steps[1].action == "final_answer"


def test_build_capability_gap_delegate_plan_should_not_force_delegate_when_agent_has_install_tool():
    """测试：若当前 Agent 自己就有 skill_install，则不应触发兜底委派。"""
    executor = _build_executor()
    agent = Agent(
        agent_id="general_agent",
        name="通用助手",
        description="具备安装能力",
        role="执行型 Agent",
        available_tools=["skill_install", "shell_exec", "send_message"],
        child_agents=[],
    )
    available_tools = [
        SimpleNamespace(name="skill_install"),
        SimpleNamespace(name="shell_exec"),
        SimpleNamespace(name="send_message"),
    ]

    plan = executor._build_capability_gap_delegate_plan(
        agent=agent,
        task="请安装 wechat-article-search 技能",
        available_tools=available_tools,
    )

    assert plan is None


def test_resolve_available_skills_should_hide_restricted_skills_for_normal_task(monkeypatch):
    """
    测试普通任务下，skill-creator/dynamic_probe 会在路由前被门禁隐藏。
    """
    executor = _build_executor()
    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role",
    )
    fake_skills = [
        SimpleNamespace(skill_id="skill-creator", name="技能创建", description="创建技能包"),
        SimpleNamespace(skill_id="dynamic_probe", name="探针", description="探针验证"),
        SimpleNamespace(skill_id="text_writing", name="写作", description="写作"),
    ]
    monkeypatch.setattr(executor.skill_manager, "list_skills", lambda: fake_skills)
    captured = {}

    def fake_route(**kwargs):
        captured["all_skills"] = kwargs.get("all_skills", [])
        return kwargs.get("all_skills", [])

    monkeypatch.setattr(executor, "_route_skills_by_metadata", fake_route)
    selected = executor._resolve_available_skills(
        agent=agent,
        task="帮我写一份订单周报并保存为 md",
    )
    routed_ids = [s.skill_id for s in captured["all_skills"]]
    selected_ids = [s.skill_id for s in selected]

    assert routed_ids == ["text_writing"]
    assert selected_ids == ["text_writing"]


def test_resolve_available_skills_should_keep_skill_creator_for_explicit_request(monkeypatch):
    """测试显式创建技能请求时，skill-creator 允许进入路由候选。"""
    executor = _build_executor()
    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role",
    )
    fake_skills = [
        SimpleNamespace(skill_id="skill-creator", name="技能创建", description="创建技能包"),
        SimpleNamespace(skill_id="text_writing", name="写作", description="写作"),
    ]
    monkeypatch.setattr(executor.skill_manager, "list_skills", lambda: fake_skills)
    captured = {}

    def fake_route(**kwargs):
        captured["all_skills"] = kwargs.get("all_skills", [])
        return kwargs.get("all_skills", [])

    monkeypatch.setattr(executor, "_route_skills_by_metadata", fake_route)
    selected = executor._resolve_available_skills(
        agent=agent,
        task="请创建一个用于订单分析的新技能，并生成初始能力包",
    )
    routed_ids = [s.skill_id for s in captured["all_skills"]]
    selected_ids = [s.skill_id for s in selected]

    assert "skill-creator" in routed_ids
    assert "skill-creator" in selected_ids


def test_resolve_available_skills_should_hide_tool_incompatible_skills(monkeypatch):
    """缺少必需工具时，技能应在路由前被隐藏，避免无工具假执行。"""
    executor = _build_executor()
    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role",
        available_tools=["datetime"],
    )
    fake_skills = [
        SimpleNamespace(
            skill_id="find-skills",
            name="找技能",
            description="真实搜索技能包",
            required_tools=["shell_exec"],
            optional_tools=[],
        ),
        SimpleNamespace(
            skill_id="text_writing",
            name="写作",
            description="写作",
            required_tools=[],
            optional_tools=[],
        ),
    ]
    monkeypatch.setattr(executor.skill_manager, "list_skills", lambda: fake_skills)
    captured = {}

    def fake_route(**kwargs):
        captured["all_skills"] = kwargs.get("all_skills", [])
        return kwargs.get("all_skills", [])

    monkeypatch.setattr(executor, "_route_skills_by_metadata", fake_route)
    selected = executor._resolve_available_skills(
        agent=agent,
        task="帮我找一个微信公众号相关的技能",
    )
    routed_ids = [s.skill_id for s in captured["all_skills"]]
    selected_ids = [s.skill_id for s in selected]

    assert "find-skills" not in routed_ids
    assert routed_ids == ["text_writing"]
    assert selected_ids == ["text_writing"]
