"""
测试 LangGraph Agent Executor
==================

测试基于 LangGraph 的 Agent 执行器
"""

import pytest
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
