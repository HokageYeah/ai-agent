"""
测试 Planning Engine
==================

测试规划引擎的各项功能
"""

import pytest
from app.agents.base import Agent, AgentConfig
from app.agents.planning import PlanningEngine, Plan, PlanStep
from app.tools.base import Tool, ToolSchema
from app.skills.base import Skill
from app.core.llm_mock import MockLLM
from app.llm_hub.inference import InferenceEngine
from app.llm_hub.registry import ModelRegistry


# 创建测试用的 Mock Tool
class MockTool(Tool):
    """Mock 工具用于测试"""
    
    @property
    def name(self) -> str:
        return "mock_tool"
    
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="mock_tool",
            description="A mock tool for testing",
            parameters={"type": "object", "properties": {}}
        )
    
    async def execute(self, params: dict):
        return {"result": "mocked"}


@pytest.mark.asyncio
async def test_plan_step_creation():
    """测试创建计划步骤"""
    step = PlanStep(action="tool", tool_name="search", params={"query": "test"})
    
    assert step.action == "tool"
    assert step.params["tool_name"] == "search"
    assert step.params["params"]["query"] == "test"
    
    step_dict = step.to_dict()
    assert step_dict["action"] == "tool"
    assert step_dict["tool_name"] == "search"


@pytest.mark.asyncio
async def test_plan_creation():
    """测试创建执行计划"""
    steps = [
        PlanStep(action="tool", tool_name="search", params={}),
        PlanStep(action="final_answer", content="Done")
    ]
    plan = Plan(steps=steps, reasoning="This is a test plan")
    
    assert len(plan.steps) == 2
    assert plan.reasoning == "This is a test plan"
    
    plan_dict = plan.to_dict()
    assert len(plan_dict["steps"]) == 2
    assert plan_dict["reasoning"] == "This is a test plan"


@pytest.mark.asyncio
async def test_planning_engine_with_mock_llm():
    """测试使用 Mock LLM 的规划引擎"""
    # 创建 Mock LLM - 使用默认响应
    mock_response = """```json
{
  "steps": [
    {"action": "tool", "tool_name": "search", "params": {"query": "test"}},
    {"action": "final_answer", "content": "Search completed"}
  ],
  "reasoning": "Use search tool to complete task"
}
```"""
    
    mock_llm = MockLLM(
        responses={},  # 使用默认响应
        delay=0.01
    )
    # 设置默认响应
    mock_llm.default_response = mock_response
    
    # 创建模型注册中心
    registry = ModelRegistry()
    
    # 创建推理引擎
    inference_engine = InferenceEngine(
        provider=mock_llm,
        model_registry=registry
    )
    
    # 创建规划引擎
    planning_engine = PlanningEngine(llm_hub=inference_engine)
    
    # 创建测试 Agent
    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="You are a test agent"
    )
    
    # 创建测试工具和技能
    tools = [MockTool()]
    skills = [
        Skill(
            skill_id="test_skill",
            name="Test Skill",
            description="A test skill",
            prompt_template="Test {input}"
        )
    ]
    
    # 创建计划
    plan = await planning_engine.create_plan(
        agent=agent,
        task="Test task",
        available_tools=tools,
        available_skills=skills
    )
    
    # 验证计划
    assert plan is not None
    assert len(plan.steps) == 2
    assert plan.steps[0].action == "tool"
    assert plan.steps[1].action == "final_answer"
    assert plan.reasoning == "Use search tool to complete task"

    
    # 创建模型注册中心
    registry = ModelRegistry()
    
    # 创建推理引擎
    inference_engine = InferenceEngine(
        provider=mock_llm,
        model_registry=registry
    )
    
    # 创建规划引擎
    planning_engine = PlanningEngine(llm_hub=inference_engine)
    
    # 创建测试 Agent
    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="You are a test agent"
    )
    
    # 创建测试工具和技能
    tools = [MockTool()]
    skills = [
        Skill(
            skill_id="test_skill",
            name="Test Skill",
            description="A test skill",
            prompt_template="Test {input}"
        )
    ]
    
    # 创建计划
    plan = await planning_engine.create_plan(
        agent=agent,
        task="Test task",
        available_tools=tools,
        available_skills=skills
    )
    
    # 验证计划
    assert plan is not None
    assert len(plan.steps) == 2
    assert plan.steps[0].action == "tool"
    assert plan.steps[1].action == "final_answer"
    assert plan.reasoning == "Use search tool to complete task"


@pytest.mark.asyncio
async def test_planning_engine_format_tools():
    """测试工具格式化"""
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    planning_engine = PlanningEngine(llm_hub=inference_engine)
    
    tools = [MockTool()]
    formatted = planning_engine._format_tools(tools)
    
    assert "mock_tool" in formatted
    assert "A mock tool for testing" in formatted


@pytest.mark.asyncio
async def test_planning_engine_format_skills():
    """测试技能格式化"""
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    planning_engine = PlanningEngine(llm_hub=inference_engine)
    
    skills = [
        Skill(
            skill_id="test_skill",
            name="Test Skill",
            description="A test skill",
            prompt_template="Test"
        )
    ]
    
    formatted = planning_engine._format_skills(skills)
    
    assert "test_skill" in formatted
    assert "Test Skill" in formatted
    assert "A test skill" in formatted


@pytest.mark.asyncio
async def test_planning_engine_parse_plan():
    """测试计划解析"""
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    planning_engine = PlanningEngine(llm_hub=inference_engine)
    
    # 测试解析有效 JSON
    json_output = """
{
  "steps": [
    {"action": "tool", "tool_name": "search", "params": {}},
    {"action": "final_answer", "content": "Done"}
  ],
  "reasoning": "Test reasoning"
}
"""
    
    plan = planning_engine._parse_plan(json_output)
    
    assert len(plan.steps) == 2
    assert plan.steps[0].action == "tool"
    assert plan.reasoning == "Test reasoning"


@pytest.mark.asyncio
async def test_planning_engine_parse_invalid_json():
    """测试解析无效 JSON"""
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    planning_engine = PlanningEngine(llm_hub=inference_engine)
    
    # 测试解析无效 JSON
    invalid_output = "This is not JSON"
    
    plan = planning_engine._parse_plan(invalid_output)
    
    # 应该返回一个包含错误信息的计划
    assert len(plan.steps) >= 1
    assert plan.steps[0].action == "final_answer"
