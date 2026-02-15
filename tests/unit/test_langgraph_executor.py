"""
测试 LangGraph Agent Executor
==================

测试基于 LangGraph 的 Agent 执行器
"""

import pytest
from app.agents.langgraph_executor import LangGraphAgentExecutor, AgentState
from app.agents.base import Agent
from app.core.llm_mock import MockLLM
from app.llm_hub.inference import InferenceEngine
from app.llm_hub.registry import ModelRegistry
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
