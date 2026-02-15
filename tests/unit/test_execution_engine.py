"""
测试 Execution Engine
==================

测试执行引擎的各项功能
"""

import pytest
from app.agents.base import Agent, AgentConfig
from app.agents.planning import Plan, PlanStep
from app.agents.execution import ExecutionEngine, ExecutionResult
from app.tools.hub import ToolHub
from app.tools.base import Tool, ToolSchema
from app.skills.base import Skill
from app.skills.manager import SkillManager
from app.core.llm_mock import MockLLM
from app.llm_hub.inference import InferenceEngine
from app.llm_hub.registry import ModelRegistry


# 创建测试工具
class TestTool(Tool):
    """测试工具"""
    
    @property
    def name(self) -> str:
        return "test_tool"
    
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="test_tool",
            description="A test tool",
            parameters={"type": "object", "properties": {}}
        )
    
    async def execute(self, params: dict):
        return "tool result"


@pytest.mark.asyncio
async def test_execution_result_creation():
    """测试创建执行结果"""
    result = ExecutionResult(
        success=True,
        result="Test completed",
        step_results=[{"action": "tool", "result": "ok"}]
    )
    
    assert result.success is True
    assert result.result == "Test completed"
    assert len(result.step_results) == 1
    
    result_dict = result.to_dict()
    assert result_dict["success"] is True
    assert result_dict["result"] == "Test completed"


@pytest.mark.asyncio
async def test_execution_engine_execute_tool():
    """测试工具执行"""
    # 创建工具中心
    tool_hub = ToolHub()
    test_tool = TestTool()
    tool_hub.register_tool(test_tool)
    
    # 创建技能管理器
    skill_manager = SkillManager()
    
    # 创建 Mock LLM
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    # 创建执行引擎
    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        llm_hub=inference_engine
    )
    
    # 创建测试 Agent
    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role"
    )
    
    # 创建计划
    plan = Plan(
        steps=[
            PlanStep(action="tool", tool_name="test_tool", params={}),
            PlanStep(action="final_answer", content="Task completed")
        ]
    )
    
    # 执行计划
    result = await execution_engine.execute_plan(agent, plan)
    
    # 验证结果
    assert result.success is True
    assert result.result == "Task completed"
    assert len(result.step_results) == 2


@pytest.mark.asyncio
async def test_execution_engine_execute_skill():
    """测试技能执行"""
    # 创建工具中心
    tool_hub = ToolHub()
    
    # 创建技能管理器
    skill_manager = SkillManager()
    test_skill = Skill(
        skill_id="test_skill",
        name="Test Skill",
        description="A test skill",
        prompt_template="Execute {task}"
    )
    skill_manager.register_skill(test_skill)
    
    # 创建 Mock LLM
    mock_llm = MockLLM(responses={}, delay=0.01)
    mock_llm.default_response = "Skill executed successfully"

    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    # 创建执行引擎
    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        llm_hub=inference_engine
    )
    
    # 创建测试 Agent
    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role"
    )
    
    # 创建计划
    plan = Plan(
        steps=[
            PlanStep(action="skill", skill_id="test_skill", params={"task": "test"}),
            PlanStep(action="final_answer", content="Skill executed")
        ]
    )
    
    # 执行计划
    result = await execution_engine.execute_plan(agent, plan)
    
    # 验证结果
    assert result.success is True
    assert len(result.step_results) == 2
    assert result.step_results[0]["action"] == "skill"


@pytest.mark.asyncio
async def test_execution_engine_nonexistent_tool():
    """测试执行不存在的工具"""
    tool_hub = ToolHub()
    skill_manager = SkillManager()
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        llm_hub=inference_engine
    )
    
    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role"
    )
    
    # 创建使用不存在工具的计划
    plan = Plan(
        steps=[
            PlanStep(action="tool", tool_name="nonexistent_tool", params={}),
            PlanStep(action="final_answer", content="Done")
        ]
    )
    
    # 执行计划
    result = await execution_engine.execute_plan(agent, plan)
    
    # 验证结果
    assert result.success is True  # 计划可以继续执行
    assert result.step_results[0]["success"] is False  # 但步骤失败
    assert "不存在" in result.step_results[0]["error"]


@pytest.mark.asyncio
async def test_execution_engine_empty_plan():
    """测试执行空计划"""
    tool_hub = ToolHub()
    skill_manager = SkillManager()
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        llm_hub=inference_engine
    )
    
    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role"
    )
    
    # 创建空计划
    plan = Plan(steps=[])
    
    # 执行计划
    result = await execution_engine.execute_plan(agent, plan)
    
    # 验证结果
    assert result.success is True
    assert len(result.step_results) == 0
