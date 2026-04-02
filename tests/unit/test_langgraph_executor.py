"""
测试 LangGraph Agent Executor
==================

测试基于 LangGraph 的 Agent 执行器
"""

import json
import pytest
from types import SimpleNamespace
from app.agents.langgraph_executor import LangGraphAgentExecutor, AgentState
from app.agents.base import Agent
from app.agents.registry import AgentRegistry
from app.agents.planning import Plan, PlanStep
from app.agents.execution import ExecutionResult
from app.core.llm_mock import MockLLM
from app.llm_hub.inference import InferenceEngine
from app.llm_hub.registry import ModelRegistry
from app.memory.agent_run_memory import AgentRunMemory
from app.memory.session_memory import TaskSummaryEntry, clear_session_memory, get_session_memory
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


def _make_session_summary_entry(
    *,
    task: str,
    summary: str,
    key_data: dict | None = None,
    conversation_turn_id: str = "",
    source_user_task: str = "",
    entry_scope: str = "primary",
) -> TaskSummaryEntry:
    """构造执行器上下文筛选测试所需的会话摘要条目。"""
    return TaskSummaryEntry(
        task_id=f"task-{task}",
        agent_id="general_agent",
        agent_name="通用助手",
        task=task,
        success=True,
        summary=summary,
        key_data=key_data or {},
        tools_used=["find-skills"],
        iterations=1,
        started_at=0.0,
        ended_at=1.0,
        conversation_turn_id=conversation_turn_id,
        source_user_task=source_user_task or task,
        entry_scope=entry_scope,
        user_actions=[],
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


def test_run_memory_failed_tool_call_should_keep_error_detail():
    """失败工具写入 run_memory 时，不应只剩一条泛化的 success=false。"""
    run_memory = AgentRunMemory(
        task="测试任务",
        agent_id="test_agent",
        agent_name="Test Agent",
    )

    run_memory.write_tool_call(
        iteration=0,
        tool_name="shell_exec",
        tool_args={"command": 'node scripts/search_wechat.js "郑州一中"'},
        tool_result={
            "success": False,
            "stderr": "Error: Cannot find module 'cheerio'",
            "return_code": 1,
        },
        success=False,
        error_msg=(
            "工具 shell_exec 返回 success=false | return_code=1 | "
            "stderr=Error: Cannot find module 'cheerio'"
        ),
    )

    messages = run_memory.build_messages_for_planning(
        system_prompt="你是测试规划器",
        current_iteration=1,
        trigger_prompt="请重规划",
    )
    tool_messages = [msg for msg in messages if msg.get("role") == "tool"]

    assert tool_messages, "应至少存在一条 tool 结果消息"
    assert "Cannot find module 'cheerio'" in str(tool_messages[-1]["content"])
    assert "工具返回详情" in str(tool_messages[-1]["content"])


def test_normalize_final_result_payload_should_extract_user_visible_text():
    """最终结果规范化时应只保留用户可见正文，并同步清洗 step_results / reflection。"""
    executor = _build_executor()

    normalized = executor._normalize_final_result_payload(
        {
            "success": True,
            "result": {
                "success": True,
                "result": "<think>内部推理</think>\n最终给用户的文章列表",
                "step_results": [
                    {"action": "skill", "result": "<think>技能推理</think>\n技能输出正文"}
                ],
                "reflection": {
                    "summary": "<think>反思推理</think>\n反思总结"
                },
                "agent_id": "general_agent",
            },
            "step_results": [
                {"action": "delegate", "result": "<think>子Agent推理</think>\n子Agent结果"}
            ],
            "reflection": {
                "summary": "<think>顶层反思</think>\n顶层总结"
            },
            "error": None,
        }
    )

    assert normalized["result"] == "最终给用户的文章列表"
    assert normalized["step_results"][0]["result"] == "子Agent结果"
    assert normalized["reflection"]["summary"] == "顶层总结"


def test_normalize_stream_step_payload_should_compact_delegate_wrapper():
    """中间 SSE 事件应压缩委派包装结果，只保留可读摘要与精简轨迹。"""
    executor = _build_executor()

    normalized = executor._normalize_stream_step_payload(
        {
            "success": True,
            "action": "delegate",
            "agent_id": "general_agent",
            "result": {
                "success": True,
                "result": "<think>内部推理</think>\n最终给用户的文章列表",
                "step_results": [
                    {
                        "action": "skill",
                        "skill_id": "wechat-article-search",
                        "result": "<think>技能推理</think>\n技能输出正文",
                    },
                    {
                        "action": "tool",
                        "tool_name": "http_request",
                        "result": {
                            "success": True,
                            "status_code": 200,
                            "url": "https://example.com",
                            "content": "<think>工具推理</think>\n" + ("A" * 1800),
                        },
                    },
                ],
                "reflection": {
                    "summary": "<think>反思推理</think>\n反思总结"
                },
                "agent_name": "通用助手",
            },
        }
    )

    assert normalized["result"] == "最终给用户的文章列表"
    assert normalized["step_results"][0]["result"] == "技能输出正文"
    assert normalized["step_results"][1]["result"]["status_code"] == 200
    assert "content_preview" in normalized["step_results"][1]["result"]
    assert "（内容已截断）" in normalized["step_results"][1]["result"]["content_preview"]
    assert normalized["reflection"]["summary"] == "反思总结"


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


def test_build_capability_gap_delegate_plan_should_delegate_follow_up_task_by_history_capability_trace():
    """显式续问若命中历史成功能力轨迹，应在规划前直接沿用正确的委派链路。"""
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
    run_memory = AgentRunMemory(
        task="继续查询 mcp技能",
        agent_id=agent.agent_id,
        agent_name=agent.name,
        context_messages=[
            {
                "role": "user",
                "content": (
                    "【历史能力轨迹】\n"
                    "能力轨迹数据: "
                    + json.dumps(
                        {
                            "source_task": "使用find-skills技能查询 新闻技能",
                            "delegated_agents": ["general_agent"],
                            "skills_used": ["find-skills"],
                            "tools_used": ["shell_exec"],
                        },
                        ensure_ascii=False,
                    )
                ),
            }
        ],
    )

    plan = executor._build_capability_gap_delegate_plan(
        agent=agent,
        task="继续查询 mcp技能",
        available_tools=available_tools,
        tool_incompatible_skills=[SimpleNamespace(skill_id="find-skills")],
        run_memory=run_memory,
    )

    assert plan is not None
    assert plan.steps[0].action == "delegate"
    assert plan.steps[0].params["agent_id"] == "general_agent"
    assert plan.steps[0].params["task"] == "继续查询 mcp技能"


def test_build_capability_gap_delegate_plan_should_prefer_history_child_agent_for_adjacent_follow_up():
    """相邻场景下，续问应优先沿用最近成功的子 Agent，而不是一律回退到 general_agent。"""
    executor = _build_executor()
    agent = Agent(
        agent_id="cs_master",
        name="客服总监",
        description="协调型 Agent",
        role="负责委派",
        available_tools=["datetime", "spawn_agent", "send_message"],
        child_agents=["order_agent", "general_agent"],
    )
    available_tools = [
        SimpleNamespace(name="datetime"),
        SimpleNamespace(name="spawn_agent"),
        SimpleNamespace(name="send_message"),
    ]
    run_memory = AgentRunMemory(
        task="继续查订单 1002 的详情",
        agent_id=agent.agent_id,
        agent_name=agent.name,
        context_messages=[
            {
                "role": "user",
                "content": (
                    "【历史能力轨迹】\n"
                    "能力轨迹数据: "
                    + json.dumps(
                        {
                            "source_task": "查询订单 1001 的状态",
                            "delegated_agents": ["order_agent"],
                            "skills_used": [],
                            "tools_used": ["database_query"],
                        },
                        ensure_ascii=False,
                    )
                ),
            }
        ],
    )

    plan = executor._build_capability_gap_delegate_plan(
        agent=agent,
        task="继续查订单 1002 的详情",
        available_tools=available_tools,
        tool_incompatible_skills=[],
        run_memory=run_memory,
    )

    assert plan is not None
    assert plan.steps[0].action == "delegate"
    assert plan.steps[0].params["agent_id"] == "order_agent"


def test_build_capability_gap_delegate_plan_should_delegate_to_specialist_child_agent():
    """专业域明显命中时，应在规划前优先委派给最匹配的子 Agent。"""
    executor = _build_executor()
    registry = AgentRegistry()
    registry.register_agent(
        Agent(
            agent_id="order_agent",
            name="订单专员",
            description="专业处理订单查询、订单详情和配送跟踪",
            role="负责订单任务",
            capabilities=["订单查询", "配送跟踪"],
            available_tools=["database_query", "http_request"],
        )
    )
    registry.register_agent(
        Agent(
            agent_id="refund_agent",
            name="退款专员",
            description="专业处理退款申请、退款审核和退款进度",
            role="负责退款任务",
            capabilities=["退款申请", "退款审核"],
            available_tools=["database_query", "calculator"],
        )
    )
    executor.child_agent_manager = SimpleNamespace(agent_registry=registry)

    agent = Agent(
        agent_id="general_agent",
        name="通用助手",
        description="负责通用任务",
        role="负责委派和执行",
        available_tools=["python_executor", "spawn_agent", "send_message"],
        child_agents=["order_agent", "refund_agent"],
    )
    available_tools = [
        SimpleNamespace(name="python_executor"),
        SimpleNamespace(name="spawn_agent"),
        SimpleNamespace(name="send_message"),
    ]

    plan = executor._build_capability_gap_delegate_plan(
        agent=agent,
        task="查询订单1002的订单详情",
        available_tools=available_tools,
        tool_incompatible_skills=[],
        run_memory=None,
    )

    assert plan is not None
    assert plan.steps[0].action == "delegate"
    assert plan.steps[0].params["agent_id"] == "order_agent"
    assert "订单" in plan.reasoning


def test_build_capability_gap_delegate_plan_should_skip_agent_already_in_call_stack():
    """专业域强制委派应自动避开当前调用链中的 Agent，防止回环。"""
    executor = _build_executor()
    registry = AgentRegistry()
    registry.register_agent(
        Agent(
            agent_id="order_agent",
            name="订单专员",
            description="专业处理订单查询和订单状态",
            role="负责订单任务",
            capabilities=["订单查询"],
            available_tools=["database_query"],
        )
    )
    executor.child_agent_manager = SimpleNamespace(
        agent_registry=registry,
        _call_stack={"order_agent", "general_agent"},
    )

    agent = Agent(
        agent_id="general_agent",
        name="通用助手",
        description="负责通用任务",
        role="负责委派和执行",
        available_tools=["python_executor", "spawn_agent", "send_message"],
        child_agents=["order_agent"],
    )
    available_tools = [
        SimpleNamespace(name="python_executor"),
        SimpleNamespace(name="spawn_agent"),
        SimpleNamespace(name="send_message"),
    ]

    plan = executor._build_capability_gap_delegate_plan(
        agent=agent,
        task="查询订单1002的订单详情并保存到桌面",
        available_tools=available_tools,
        tool_incompatible_skills=[],
        run_memory=None,
    )

    assert plan is None


def test_build_task_relevant_context_messages_should_append_follow_up_capability_message_when_topic_changes():
    """换主题续问时，主题摘要可为空，但应追加独立的能力轨迹上下文。"""
    conversation_id = "conv-followup-capability-context"
    clear_session_memory(conversation_id)
    try:
        executor = _build_executor()
        session_memory = get_session_memory(conversation_id)
        entry = _make_session_summary_entry(
            task="使用find-skills技能查询 新闻技能",
            summary="已查到新闻相关技能",
        )
        entry.capability_trace = {
            "delegated_agents": ["general_agent"],
            "skills_used": ["find-skills"],
            "tools_used": ["shell_exec"],
        }
        session_memory.append_task_summary(entry)

        messages = executor._build_task_relevant_context_messages(
            task="继续查询 mcp技能",
            conversation_id=conversation_id,
            conversation_history=None,
        )

        assert len(messages) == 1
        assert "【历史能力轨迹】" in messages[0]["content"]
        assert "find-skills" in messages[0]["content"]
    finally:
        clear_session_memory(conversation_id)


def test_build_task_relevant_context_messages_should_append_conversation_recall_context_for_history_question():
    """历史回顾类问题应注入按轮次整理的会话主线，而不是空上下文。"""
    conversation_id = "conv-history-recall-context"
    clear_session_memory(conversation_id)
    try:
        executor = _build_executor()
        session_memory = get_session_memory(conversation_id)
        session_memory.append_task_summary(
            _make_session_summary_entry(
                task="使用find-skills技能查询 新闻技能",
                summary="已查到新闻相关技能",
                conversation_turn_id="turn-1",
                source_user_task="使用find-skills技能查询 新闻技能",
                entry_scope="primary",
            )
        )
        session_memory.append_task_summary(
            _make_session_summary_entry(
                task="查询关键词“新闻”对应的技能结果，并整理安装量",
                summary="子任务执行成功，已找到 news-summary",
                conversation_turn_id="turn-1",
                source_user_task="使用find-skills技能查询 新闻技能",
                entry_scope="subtask",
            )
        )
        session_memory._entries[1].capability_trace = {
            "delegated_agents": ["general_agent"],
            "skills_used": ["find-skills"],
            "tools_used": ["shell_exec"],
        }

        messages = executor._build_task_relevant_context_messages(
            task="我的第一个问题是什么",
            conversation_id=conversation_id,
            conversation_history=None,
        )

        assert len(messages) == 1
        assert "【会话主线回顾】" in messages[0]["content"]
        assert "使用find-skills技能查询 新闻技能" in messages[0]["content"]
        assert "技能=find-skills" in messages[0]["content"]
    finally:
        clear_session_memory(conversation_id)


def test_build_task_relevant_context_messages_should_support_generic_third_question_recall():
    """执行器注入历史回顾时，应支持通用的“第 N 个问题”定位结果。"""
    conversation_id = "conv-history-third-question"
    clear_session_memory(conversation_id)
    try:
        executor = _build_executor()
        session_memory = get_session_memory(conversation_id)
        session_memory.append_task_summary(
            _make_session_summary_entry(
                task="使用find-skills技能查询 新闻技能",
                summary="已查到新闻相关技能",
                conversation_turn_id="turn-1",
            )
        )
        session_memory.append_task_summary(
            _make_session_summary_entry(
                task="订单1002的商品详情，并且找到订单客户",
                summary="已查到订单1002的商品与客户信息",
                conversation_turn_id="turn-2",
            )
        )
        session_memory.append_task_summary(
            _make_session_summary_entry(
                task="继续查询 mcp技能",
                summary="已查到 mcp 相关技能",
                conversation_turn_id="turn-3",
            )
        )

        messages = executor._build_task_relevant_context_messages(
            task="我的第三个问题是什么",
            conversation_id=conversation_id,
            conversation_history=None,
        )

        assert len(messages) == 1
        assert "【会话主线回顾】" in messages[0]["content"]
        assert "当前定位问题: 第3个问题 -> 继续查询 mcp技能" in messages[0]["content"]
    finally:
        clear_session_memory(conversation_id)


def test_build_task_relevant_context_messages_should_keep_multi_target_recall_context():
    """执行器注入历史回顾时，应保留多目标定位结果供后续规划统一消费。"""
    conversation_id = "conv-history-multi-question"
    clear_session_memory(conversation_id)
    try:
        executor = _build_executor()
        session_memory = get_session_memory(conversation_id)
        session_memory.append_task_summary(
            _make_session_summary_entry(
                task="使用find-skills技能查询 新闻技能",
                summary="已查到新闻相关技能",
                conversation_turn_id="turn-1",
            )
        )
        session_memory.append_task_summary(
            _make_session_summary_entry(
                task="订单1002的商品详情，并且找到订单客户",
                summary="已查到订单1002的商品与客户信息",
                conversation_turn_id="turn-2",
            )
        )
        session_memory.append_task_summary(
            _make_session_summary_entry(
                task="继续查询 mcp技能",
                summary="已查到 mcp 相关技能",
                conversation_turn_id="turn-3",
            )
        )
        session_memory.append_task_summary(
            _make_session_summary_entry(
                task="订单1002的商品是谁买的",
                summary="已查到订单1002的购买者",
                conversation_turn_id="turn-4",
            )
        )
        session_memory.append_task_summary(
            _make_session_summary_entry(
                task="我的第一个问题是什么",
                summary="已回答首个问题",
                conversation_turn_id="turn-5",
            )
        )

        messages = executor._build_task_relevant_context_messages(
            task="第四、第五个问题分别是什么",
            conversation_id=conversation_id,
            conversation_history=None,
        )

        assert len(messages) == 1
        assert "当前定位问题: 第4个问题 -> 订单1002的商品是谁买的" in messages[0]["content"]
        assert "当前定位问题: 第5个问题 -> 我的第一个问题是什么" in messages[0]["content"]
        assert "当前定位轮次数据列表:" in messages[0]["content"]
    finally:
        clear_session_memory(conversation_id)


def test_build_history_answer_plan_should_keep_repeated_ordinal_multi_target_answer():
    """历史直答应支持“第二个、第三个问题”并完整输出多个目标。"""
    executor = _build_executor()
    run_memory = AgentRunMemory(
        task="我的第二个、第三个问题是什么",
        agent_id="general_agent",
        agent_name="通用助手",
        context_messages=[
            {
                "role": "user",
                "content": (
                    "【会话主线回顾】\n"
                    "1. 用户问题: 使用find-skills技能查询 新闻技能\n"
                    "2. 用户问题: 订单1002的商品详情，并且找到订单客户\n"
                    "3. 用户问题: 订单1002的商品是谁买的\n"
                    "当前定位问题: 第2个问题 -> 订单1002的商品详情，并且找到订单客户\n"
                    "当前定位问题: 第3个问题 -> 订单1002的商品是谁买的\n"
                    '当前定位轮次数据列表: [{"turn_index": 2, "target_kind": "question", "target_label": "第2个问题", "source_user_task": "订单1002的商品详情，并且找到订单客户", "summary": "已查到订单1002的商品与客户信息"}, {"turn_index": 3, "target_kind": "question", "target_label": "第3个问题", "source_user_task": "订单1002的商品是谁买的", "summary": "已查到订单1002的购买者"}]'
                ),
            }
        ],
    )

    plan = executor._build_history_answer_plan(
        task="我的第二个、第三个问题是什么",
        run_memory=run_memory,
    )

    assert plan is not None
    assert len(plan.steps) == 1
    assert plan.steps[0].action == "final_answer"
    assert "您的第2个问题是：订单1002的商品详情，并且找到订单客户" in plan.steps[0].params["content"]
    assert "您的第3个问题是：订单1002的商品是谁买的" in plan.steps[0].params["content"]


@pytest.mark.asyncio
async def test_plan_node_should_force_delegate_by_history_capability_trace(monkeypatch):
    """主 Agent 遇到换主题续问时，应在进入 LLM 前沿用历史成功能力链路。"""
    conversation_id = "conv-plan-followup-capability"
    clear_session_memory(conversation_id)
    try:
        executor = _build_executor()
        agent = Agent(
            agent_id="cs_master",
            name="客服总监",
            description="协调型 Agent",
            role="负责委派",
            available_tools=["datetime", "spawn_agent", "send_message"],
            child_agents=["general_agent"],
        )
        session_memory = get_session_memory(conversation_id)
        entry = _make_session_summary_entry(
            task="使用find-skills技能查询 新闻技能",
            summary="已查到新闻相关技能",
        )
        entry.capability_trace = {
            "delegated_agents": ["general_agent"],
            "skills_used": ["find-skills"],
            "tools_used": ["shell_exec"],
        }
        session_memory.append_task_summary(entry)

        monkeypatch.setattr(
            executor.tool_hub,
            "list_tools",
            lambda: [
                SimpleNamespace(name="datetime"),
                SimpleNamespace(name="spawn_agent"),
                SimpleNamespace(name="send_message"),
            ],
        )
        monkeypatch.setattr(
            executor,
            "_resolve_available_skills",
            lambda agent, task: ([], [SimpleNamespace(skill_id="find-skills")]),
        )

        async def fail_create_plan(**kwargs):
            raise AssertionError("命中历史能力轨迹时不应再进入 LLM 规划")

        monkeypatch.setattr(executor.planning_engine, "create_plan", fail_create_plan)

        context_messages = executor._build_task_relevant_context_messages(
            task="继续查询 mcp技能",
            conversation_id=conversation_id,
            conversation_history=None,
        )
        state: AgentState = {
            "messages": context_messages,
            "current_plan": None,
            "tool_outputs": [],
            "iterations": 0,
            "final_result": None,
            "task": "继续查询 mcp技能",
            "agent": agent,
            "error_context": [],
            "error_analysis": None,
            "reflection_history": [],
            "pending_confirmations": {},
            "pending_user_inputs": {},
            "user_rejected_tools": [],
            "run_memory": AgentRunMemory(
                task="继续查询 mcp技能",
                agent_id=agent.agent_id,
                agent_name=agent.name,
                context_messages=context_messages,
            ),
        }

        new_state = await executor._plan_node(state, stream_callback=None)

        assert new_state["current_plan"] is not None
        assert new_state["current_plan"].steps[0].action == "delegate"
        assert new_state["current_plan"].steps[0].params["agent_id"] == "general_agent"
    finally:
        clear_session_memory(conversation_id)


@pytest.mark.asyncio
async def test_plan_node_should_direct_answer_from_history_for_repeated_order_question(monkeypatch):
    """同题重复问时，应优先走历史直答，而不是再次委派查询。"""
    executor = _build_executor()
    agent = Agent(
        agent_id="cs_master",
        name="客服总监",
        description="协调型 Agent",
        role="负责委派",
        available_tools=["datetime", "spawn_agent"],
        child_agents=["order_agent"],
    )

    monkeypatch.setattr(
        executor.tool_hub,
        "list_tools",
        lambda: [
            SimpleNamespace(name="datetime"),
            SimpleNamespace(name="spawn_agent"),
        ],
    )
    monkeypatch.setattr(
        executor,
        "_resolve_available_skills",
        lambda agent, task: ([], []),
    )

    async def fail_create_plan(**kwargs):
        raise AssertionError("命中历史直答时不应再进入 LLM 规划")

    monkeypatch.setattr(executor.planning_engine, "create_plan", fail_create_plan)

    context_messages = [
        {
            "role": "user",
            "content": (
                "【历史任务摘要】\n"
                "任务: 订单1002的商品是谁买的\n"
                "结果: ✅ 成功\n"
                "结论: 成功查询到订单1002的商品购买者是李娜\n"
                "关键数据: "
                + json.dumps(
                    {
                        "result_preview": "订单1002的商品是由李娜购买的。",
                        "structured_result": [
                            {
                                "action": "tool",
                                "name": "database_query",
                                "result": {"order_id": "1002", "buyer_name": "李娜"},
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            ),
        }
    ]
    state: AgentState = {
        "messages": context_messages,
        "current_plan": None,
        "tool_outputs": [],
        "iterations": 0,
        "final_result": None,
        "task": "订单1002的商品是谁买的",
        "conversation_id": "conv-repeat-order-question",
        "agent": agent,
        "error_context": [],
        "error_analysis": None,
        "reflection_history": [],
        "pending_confirmations": {},
        "pending_user_inputs": {},
        "user_rejected_tools": [],
        "run_memory": AgentRunMemory(
            task="订单1002的商品是谁买的",
            agent_id=agent.agent_id,
            agent_name=agent.name,
            context_messages=context_messages,
        ),
    }

    new_state = await executor._plan_node(state, stream_callback=None)

    assert new_state["current_plan"] is not None
    assert len(new_state["current_plan"].steps) == 1
    assert new_state["current_plan"].steps[0].action == "final_answer"
    assert "历史" in new_state["current_plan"].reasoning


@pytest.mark.asyncio
async def test_plan_node_should_pass_history_answer_candidates_to_planning_engine_for_related_task(monkeypatch):
    """未达到直答阈值时，也应把历史答案候选注入规划上下文供 LLM 决策。"""
    executor = _build_executor()
    agent = Agent(
        agent_id="cs_master",
        name="客服总监",
        description="协调型 Agent",
        role="负责委派",
        available_tools=["datetime", "spawn_agent"],
        child_agents=["order_agent"],
    )

    monkeypatch.setattr(
        executor.tool_hub,
        "list_tools",
        lambda: [
            SimpleNamespace(name="datetime"),
            SimpleNamespace(name="spawn_agent"),
        ],
    )
    monkeypatch.setattr(
        executor,
        "_resolve_available_skills",
        lambda agent, task: ([], []),
    )

    captured_context = {}

    async def fake_create_plan(**kwargs):
        captured_context.update(kwargs.get("context", {}))
        return Plan(
            steps=[PlanStep("final_answer", content="由规划引擎决定是否复用历史答案")],
            reasoning="根据上下文自主决策",
        )

    monkeypatch.setattr(executor.planning_engine, "create_plan", fake_create_plan)

    context_messages = [
        {
            "role": "user",
            "content": (
                "【历史任务摘要】\n"
                "任务: 查询订单1002的详细信息\n"
                "结果: ✅ 成功\n"
                "结论: 成功查询到订单1002的完整信息，包括买家李娜与订单商品信息\n"
                "关键数据: "
                + json.dumps(
                    {
                        "result_preview": "订单1002的买家是李娜，商品为华为 Mate 60 Pro 512GB。",
                        "structured_result": [
                            {
                                "action": "tool",
                                "name": "database_query",
                                "result": {"order_id": "1002", "buyer_name": "李娜"},
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            ),
        }
    ]
    state: AgentState = {
        "messages": context_messages,
        "current_plan": None,
        "tool_outputs": [],
        "iterations": 0,
        "final_result": None,
        "task": "订单1002的商品是谁买的",
        "conversation_id": "conv-related-order-question",
        "agent": agent,
        "error_context": [],
        "error_analysis": None,
        "reflection_history": [],
        "pending_confirmations": {},
        "pending_user_inputs": {},
        "user_rejected_tools": [],
        "run_memory": AgentRunMemory(
            task="订单1002的商品是谁买的",
            agent_id=agent.agent_id,
            agent_name=agent.name,
            context_messages=context_messages,
        ),
    }

    await executor._plan_node(state, stream_callback=None)

    assert "history_answer_candidates" in captured_context
    assert len(captured_context["history_answer_candidates"]) == 1
    assert captured_context["history_answer_candidates"][0]["source_task"] == "查询订单1002的详细信息"
    assert "李娜" in captured_context["history_answer_candidates"][0]["answer_preview"]


@pytest.mark.asyncio
async def test_plan_node_should_direct_answer_for_conversation_recall_target(monkeypatch):
    """命中目标轮次的会话回顾候选后，应直接生成历史直答计划。"""
    executor = _build_executor()
    agent = Agent(
        agent_id="cs_master",
        name="客服总监",
        description="协调型 Agent",
        role="负责委派",
        available_tools=["datetime", "spawn_agent"],
        child_agents=["general_agent"],
    )

    monkeypatch.setattr(
        executor.tool_hub,
        "list_tools",
        lambda: [
            SimpleNamespace(name="datetime"),
            SimpleNamespace(name="spawn_agent"),
        ],
    )
    monkeypatch.setattr(
        executor,
        "_resolve_available_skills",
        lambda agent, task: ([], []),
    )

    context_messages = [
        {
            "role": "user",
            "content": (
                "【会话主线回顾】\n"
                "以下为当前会话按时间顺序整理的主要对话主线。\n"
                "1. 用户问题: 使用find-skills技能查询 新闻技能\n"
                "2. 用户问题: 订单1002的商品详情，并且找到订单客户\n"
                "3. 用户问题: 继续查询 mcp技能\n"
                "当前定位问题: 第3个问题 -> 继续查询 mcp技能\n"
                "当前定位轮次数据: "
                + json.dumps(
                    {
                        "turn_index": 3,
                        "turn_id": "turn-3",
                        "target_kind": "question",
                        "target_label": "第3个问题",
                        "source_user_task": "继续查询 mcp技能",
                        "summary": "已查到 mcp 相关技能",
                    },
                    ensure_ascii=False,
                )
            ),
        }
    ]
    state: AgentState = {
        "messages": context_messages,
        "current_plan": None,
        "tool_outputs": [],
        "iterations": 0,
        "final_result": None,
        "task": "我的第三个问题是什么",
        "conversation_id": "conv-direct-recall-answer",
        "agent": agent,
        "error_context": [],
        "error_analysis": None,
        "reflection_history": [],
        "pending_confirmations": {},
        "pending_user_inputs": {},
        "user_rejected_tools": [],
        "run_memory": AgentRunMemory(
            task="我的第三个问题是什么",
            agent_id=agent.agent_id,
            agent_name=agent.name,
            context_messages=context_messages,
        ),
    }

    new_state = await executor._plan_node(state, stream_callback=None)

    assert new_state["current_plan"] is not None
    assert len(new_state["current_plan"].steps) == 1
    assert new_state["current_plan"].steps[0].action == "final_answer"
    assert "第3个问题" in new_state["current_plan"].steps[0].params["content"]
    assert "继续查询 mcp技能" in new_state["current_plan"].steps[0].params["content"]


@pytest.mark.asyncio
async def test_plan_node_should_direct_answer_for_multi_recall_targets(monkeypatch):
    """多目标历史追问在目标全部覆盖时，应一次性直答全部目标。"""
    executor = _build_executor()
    agent = Agent(
        agent_id="cs_master",
        name="客服总监",
        description="协调型 Agent",
        role="负责委派",
        available_tools=["datetime", "spawn_agent"],
        child_agents=["general_agent"],
    )

    monkeypatch.setattr(
        executor.tool_hub,
        "list_tools",
        lambda: [
            SimpleNamespace(name="datetime"),
            SimpleNamespace(name="spawn_agent"),
        ],
    )
    monkeypatch.setattr(
        executor,
        "_resolve_available_skills",
        lambda agent, task: ([], []),
    )

    context_messages = [
        {
            "role": "user",
            "content": (
                "【会话主线回顾】\n"
                "以下为当前会话按时间顺序整理的主要对话主线。\n"
                "4. 用户问题: 订单1002的商品是谁买的\n"
                "5. 用户问题: 我的第一个问题是什么\n"
                "当前定位问题: 第4个问题 -> 订单1002的商品是谁买的\n"
                "当前定位问题: 第5个问题 -> 我的第一个问题是什么\n"
                "当前定位轮次数据列表: "
                + json.dumps(
                    [
                        {
                            "turn_index": 4,
                            "turn_id": "turn-4",
                            "target_kind": "question",
                            "target_label": "第4个问题",
                            "source_user_task": "订单1002的商品是谁买的",
                            "summary": "已查到购买者",
                        },
                        {
                            "turn_index": 5,
                            "turn_id": "turn-5",
                            "target_kind": "question",
                            "target_label": "第5个问题",
                            "source_user_task": "我的第一个问题是什么",
                            "summary": "已回答首个问题",
                        },
                    ],
                    ensure_ascii=False,
                )
            ),
        }
    ]
    state: AgentState = {
        "messages": context_messages,
        "current_plan": None,
        "tool_outputs": [],
        "iterations": 0,
        "final_result": None,
        "task": "第四、第五个问题分别是什么",
        "conversation_id": "conv-direct-multi-recall-answer",
        "agent": agent,
        "error_context": [],
        "error_analysis": None,
        "reflection_history": [],
        "pending_confirmations": {},
        "pending_user_inputs": {},
        "user_rejected_tools": [],
        "run_memory": AgentRunMemory(
            task="第四、第五个问题分别是什么",
            agent_id=agent.agent_id,
            agent_name=agent.name,
            context_messages=context_messages,
        ),
    }

    new_state = await executor._plan_node(state, stream_callback=None)

    assert new_state["current_plan"] is not None
    assert len(new_state["current_plan"].steps) == 1
    content = new_state["current_plan"].steps[0].params["content"]
    assert "第4个问题" in content
    assert "订单1002的商品是谁买的" in content
    assert "第5个问题" in content
    assert "我的第一个问题是什么" in content


@pytest.mark.asyncio
async def test_plan_node_should_not_short_circuit_when_multi_recall_targets_are_incomplete(monkeypatch):
    """多目标历史追问若目标覆盖不全，不应继续走历史直答短路。"""
    executor = _build_executor()
    agent = Agent(
        agent_id="cs_master",
        name="客服总监",
        description="协调型 Agent",
        role="负责委派",
        available_tools=["datetime", "spawn_agent"],
        child_agents=["general_agent"],
    )

    monkeypatch.setattr(
        executor.tool_hub,
        "list_tools",
        lambda: [
            SimpleNamespace(name="datetime"),
            SimpleNamespace(name="spawn_agent"),
        ],
    )
    monkeypatch.setattr(
        executor,
        "_resolve_available_skills",
        lambda agent, task: ([], []),
    )

    captured_context = {}

    async def fake_create_plan(**kwargs):
        captured_context.update(kwargs.get("context", {}))
        return Plan(
            steps=[PlanStep("final_answer", content="由规划引擎基于多目标上下文回答")],
            reasoning="多目标覆盖不足，回退常规规划",
        )

    monkeypatch.setattr(executor.planning_engine, "create_plan", fake_create_plan)

    context_messages = [
        {
            "role": "user",
            "content": (
                "【会话主线回顾】\n"
                "以下为当前会话按时间顺序整理的主要对话主线。\n"
                "5. 用户问题: 我的第一个问题是什么\n"
                "当前定位问题: 第5个问题 -> 我的第一个问题是什么\n"
                "当前定位轮次数据: "
                + json.dumps(
                    {
                        "turn_index": 5,
                        "turn_id": "turn-5",
                        "target_kind": "question",
                        "target_label": "第5个问题",
                        "source_user_task": "我的第一个问题是什么",
                        "summary": "已回答首个问题",
                    },
                    ensure_ascii=False,
                )
            ),
        }
    ]
    state: AgentState = {
        "messages": context_messages,
        "current_plan": None,
        "tool_outputs": [],
        "iterations": 0,
        "final_result": None,
        "task": "第四、第五个问题分别是什么",
        "conversation_id": "conv-incomplete-multi-recall-answer",
        "agent": agent,
        "error_context": [],
        "error_analysis": None,
        "reflection_history": [],
        "pending_confirmations": {},
        "pending_user_inputs": {},
        "user_rejected_tools": [],
        "run_memory": AgentRunMemory(
            task="第四、第五个问题分别是什么",
            agent_id=agent.agent_id,
            agent_name=agent.name,
            context_messages=context_messages,
        ),
    }

    new_state = await executor._plan_node(state, stream_callback=None)

    assert new_state["current_plan"] is not None
    assert new_state["current_plan"].steps[0].params["content"] == "由规划引擎基于多目标上下文回答"
    assert "history_answer_candidates" in captured_context


def test_build_history_guided_install_context_should_collect_ranked_candidates():
    """安装任务应提炼历史 package_ref 候选，供规划 LLM 自主决定是否复用。"""
    executor = _build_executor()
    run_memory = AgentRunMemory(
        task="使用githb搜索安装 yyh211/claude-meta-skill@daily-ai-news 技能",
        agent_id="general_agent",
        agent_name="通用助手",
        context_messages=[
            {
                "role": "user",
                "content": (
                    "【历史任务摘要】\n"
                    "任务: 使用find-skills技能，查询新闻有关技能\n"
                    "结果: ✅ 成功\n"
                    "结论: 已查询到新闻相关技能\n"
                    "可直接复用事实:\n"
                    "- package_ref: AI/科技领域新闻 -> yyh211/claude-meta-skill@daily-ai-news\n"
                    "- command: 安装命令 -> npx skills add yyh211/claude-meta-skill@daily-ai-news\n"
                ),
            }
        ],
    )

    context = executor._build_history_guided_install_context(
        task="使用githb搜索安装 yyh211/claude-meta-skill@daily-ai-news 技能",
        run_memory=run_memory,
    )

    assert "history_install_candidates" in context
    assert len(context["history_install_candidates"]) == 1
    assert context["history_install_candidates"][0]["package_ref"] == "yyh211/claude-meta-skill@daily-ai-news"
    assert context["history_install_candidates"][0]["skill_name"] == "daily-ai-news"
    assert context["history_install_candidates"][0]["label"] == "AI/科技领域新闻"
    assert context["history_install_candidates"][0]["score"] > 0


def test_build_history_guided_install_context_should_ignore_non_install_task():
    """非安装任务不应提炼历史安装候选，避免无关上下文污染规划。"""
    executor = _build_executor()
    run_memory = AgentRunMemory(
        task="列出刚才找到的所有技能",
        agent_id="general_agent",
        agent_name="通用助手",
        context_messages=[
            {
                "role": "user",
                "content": (
                    "【历史任务摘要】\n"
                    "可直接复用事实:\n"
                    "- package_ref: 金融财经新闻 -> sundial-org/awesome-openclaw-skills@finance-news\n"
                ),
            }
        ],
    )

    context = executor._build_history_guided_install_context(
        task="列出刚才找到的所有技能",
        run_memory=run_memory,
    )

    assert context == {}


@pytest.mark.asyncio
async def test_plan_node_should_pass_history_install_candidates_to_planning_engine(monkeypatch):
    """
    测试当前安装任务即使命中历史 package_ref，也应继续进入规划引擎，
    由 LLM 结合当前回合意图决定“直接安装”还是“先搜索/先核验”。
    """
    executor = _build_executor()
    agent = Agent(
        agent_id="general_agent",
        name="通用助手",
        description="具备安装能力",
        role="执行型 Agent",
        available_tools=["skill_install", "shell_exec"],
    )
    run_memory = AgentRunMemory(
        task="使用githb搜索安装 yyh211/claude-meta-skill@daily-ai-news 技能",
        agent_id=agent.agent_id,
        agent_name=agent.name,
        context_messages=[
            {
                "role": "user",
                "content": (
                    "【历史任务摘要】\n"
                    "可直接复用事实:\n"
                    "- package_ref: AI/科技领域新闻 -> yyh211/claude-meta-skill@daily-ai-news\n"
                ),
            }
        ],
    )
    captured: dict = {}

    monkeypatch.setattr(executor.tool_hub, "list_tools", lambda: [SimpleNamespace(name="skill_install")])
    monkeypatch.setattr(executor, "_resolve_available_skills", lambda agent, task: ([], []))

    async def fake_create_plan(**kwargs):
        captured["context"] = kwargs.get("context") or {}
        return Plan(
            steps=[PlanStep("final_answer", content="由规划引擎决定下一步")],
            reasoning="由 LLM 结合当前任务和历史上下文决定路径",
        )

    monkeypatch.setattr(executor.planning_engine, "create_plan", fake_create_plan)

    state: AgentState = {
        "messages": [],
        "current_plan": None,
        "tool_outputs": [],
        "iterations": 0,
        "final_result": None,
        "task": "使用githb搜索安装 yyh211/claude-meta-skill@daily-ai-news 技能",
        "agent": agent,
        "error_context": [],
        "error_analysis": None,
        "reflection_history": [],
        "pending_confirmations": {},
        "pending_user_inputs": {},
        "user_rejected_tools": [],
        "run_memory": run_memory,
    }

    new_state = await executor._plan_node(state, stream_callback=None)

    assert "history_install_candidates" in captured["context"]
    assert captured["context"]["history_install_candidates"][0]["package_ref"] == (
        "yyh211/claude-meta-skill@daily-ai-news"
    )
    assert new_state["current_plan"].reasoning == "由 LLM 结合当前任务和历史上下文决定路径"


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


def test_resolve_available_skills_should_hide_script_skill_without_shell_exec(monkeypatch):
    """外部下载技能未声明工具但带脚本时，协调型 Agent 无 shell_exec 应先隐藏并走委派。"""
    executor = _build_executor()
    agent = Agent(
        agent_id="cs_master",
        name="客服总监",
        description="协调型 Agent",
        role="只负责委派",
        available_tools=["datetime", "spawn_agent"],
    )
    fake_skills = [
        SimpleNamespace(
            skill_id="wechat-article-search",
            name="微信公众号搜索",
            description="下载的外部技能",
            required_tools=[],
            optional_tools=[],
            scripts=["scripts/search_wechat.js"],
            runtime_dependencies=[],
        ),
        SimpleNamespace(
            skill_id="text_writing",
            name="写作",
            description="写作",
            required_tools=[],
            optional_tools=[],
            scripts=[],
            runtime_dependencies=[],
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
        task="查找郑州一中微信公众号文章",
    )
    routed_ids = [s.skill_id for s in captured["all_skills"]]
    selected_ids = [s.skill_id for s in selected]

    assert "wechat-article-search" not in routed_ids
    assert routed_ids == ["text_writing"]
    assert selected_ids == ["text_writing"]


def test_build_task_relevant_context_messages_should_merge_selected_session_summary_and_history():
    """执行器应统一合并“会话相关摘要 + 对话历史裁剪结果”，而不是全量注入。"""
    executor = _build_executor()
    conversation_id = "executor-context-selection"
    clear_session_memory(conversation_id)

    try:
        session_memory = get_session_memory(conversation_id)
        session_memory.append_task_summary(
            _make_session_summary_entry(
                task="使用find-skills技能查询 新闻技能",
                summary="已查到新闻相关技能，最高安装量是 news-summary(405次)",
                key_data={
                    "actionable_facts": [
                        {
                            "kind": "package_ref",
                            "label": "新闻技能",
                            "value": "zjfls/zhoujie-claude-skills@news-summary",
                        }
                    ]
                },
            )
        )
        session_memory.append_task_summary(
            _make_session_summary_entry(
                task="继续查找查询 浏览器相关技能",
                summary="已查到浏览器相关技能，最高安装量是 agent-browser(142.8K)",
                key_data={
                    "actionable_facts": [
                        {
                            "kind": "package_ref",
                            "label": "浏览器技能",
                            "value": "vercel-labs/agent-browser@agent-browser",
                        }
                    ]
                },
            )
        )

        conversation_history = [
            {"role": "user", "content": "第一轮：查新闻技能"},
            {"role": "assistant", "content": "无关铺垫" * 300},
            {"role": "user", "content": "第二轮：查浏览器技能"},
            {"role": "assistant", "content": "浏览器技能结果：" + "agent-browser 很热门。 " * 200},
        ]

        context_messages = executor._build_task_relevant_context_messages(
            task="继续，告诉我刚才那个浏览器相关技能里安装量最高的是哪个",
            conversation_id=conversation_id,
            conversation_history=conversation_history,
        )

        assert context_messages
        assert any(
            "【历史任务摘要】" in str(message.get("content", ""))
            and "浏览器相关技能" in str(message.get("content", ""))
            for message in context_messages
        )
        assert any(
            "浏览器技能结果：" in str(message.get("content", ""))
            and "中间内容仅因控制提示词长度而省略" in str(message.get("content", ""))
            for message in context_messages
        )
        assert not any(
            "新闻技能" in str(message.get("content", ""))
            and "【历史任务摘要】" in str(message.get("content", ""))
            for message in context_messages
        )
        assert not any(
            "第一轮：查新闻技能" in str(message.get("content", ""))
            or "无关铺垫" in str(message.get("content", ""))
            for message in context_messages
        )
    finally:
        clear_session_memory(conversation_id)


def test_build_task_relevant_context_messages_should_merge_inherited_context_without_duplication():
    """子 Agent 继承父级上下文时，应与会话检索结果去重合并。"""
    executor = _build_executor()
    conversation_id = "executor-inherited-context"
    clear_session_memory(conversation_id)

    try:
        session_memory = get_session_memory(conversation_id)
        entry = _make_session_summary_entry(
            task="订单1002的商品是谁买的",
            summary="成功查询到订单1002的商品购买者是李娜",
            key_data={
                "result_preview": "订单1002的商品是由李娜购买的。",
            },
        )
        session_memory.append_task_summary(entry)
        inherited_context_messages = [entry.to_context_message()]

        context_messages = executor._build_task_relevant_context_messages(
            task="订单1002的商品是谁买的",
            conversation_id=conversation_id,
            conversation_history=None,
            extra_context_messages=inherited_context_messages,
        )

        matched_messages = [
            message
            for message in context_messages
            if "订单1002的商品购买者是李娜" in str(message.get("content", ""))
        ]
        assert len(matched_messages) == 1
    finally:
        clear_session_memory(conversation_id)
