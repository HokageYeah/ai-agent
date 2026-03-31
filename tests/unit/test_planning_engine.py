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


class _StubInferenceResult:
    """规划引擎单测用的简化推理结果对象。"""

    def __init__(self, content: str, finish_reason: str = "stop"):
        self.content = content
        self.finish_reason = finish_reason


class _SequenceLLMHub:
    """
    依次返回预设结果的 LLM Hub Stub。

    说明：
    - 用于验证 PlanningEngine 在首轮输出被截断时，是否会触发自动重试。
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self.call_count = 0

    async def infer(self, messages, config):
        idx = min(self.call_count, len(self._responses) - 1)
        self.call_count += 1
        return self._responses[idx]


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
    {"action": "tool", "tool_name": "mock_tool", "params": {"query": "test"}},
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


@pytest.mark.asyncio
async def test_planning_engine_parse_think_and_semistructured_steps():
    """测试 `<think>` + 半结构化“执行步骤”文本可被正确解析。"""
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    planning_engine = PlanningEngine(llm_hub=inference_engine)

    mixed_output = """
<think>
这里是思考过程
</think>

【规划-第1轮】
推理过程: 先检查依赖，再执行搜索脚本。
执行步骤: [{"action": "tool", "tool_name": "shell_exec", "params": {"command": "node scripts/search_wechat.js \\"郑州一中\\" -n 10", "working_dir": "/tmp/wechat"}}, {"action": "final_answer", "content": "根据搜索结果回答用户"}]
"""

    plan = planning_engine._parse_plan(mixed_output)

    assert len(plan.steps) == 2
    assert plan.steps[0].action == "tool"
    assert plan.steps[0].params["tool_name"] == "shell_exec"
    assert "先检查依赖" in plan.reasoning


@pytest.mark.asyncio
async def test_planning_engine_parse_think_json_with_embedded_markdown_code_fence():
    """顶层 JSON 字符串里带 markdown 代码块时，不应误把内层 fenced block 当成载荷。"""
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    planning_engine = PlanningEngine(llm_hub=inference_engine)

    mixed_output = """
<think>
这里是思考过程
</think>

{
  "steps": [
    {
      "action": "final_answer",
      "content": "安装命令如下：\\n```bash\\nnpx skills add yyh211/claude-meta-skill@daily-ai-news\\n```"
    }
  ],
  "reasoning": "直接基于历史记录回答"
}
"""

    plan = planning_engine._parse_plan(mixed_output)

    assert len(plan.steps) == 1
    assert plan.steps[0].action == "final_answer"
    assert "npx skills add yyh211/claude-meta-skill@daily-ai-news" in plan.steps[0].params["content"]
    assert plan.reasoning == "直接基于历史记录回答"


@pytest.mark.asyncio
async def test_planning_engine_parse_unclosed_think_plus_json():
    """未闭合 `<think>` 前缀后紧跟 JSON 时，也应能恢复出计划。"""
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    planning_engine = PlanningEngine(llm_hub=inference_engine)

    mixed_output = """
<think>
先分析历史上下文，再输出计划。

{
  "steps": [
    {"action": "tool", "tool_name": "mock_tool", "params": {"query": "AI 新闻"}},
    {"action": "final_answer", "content": "完成"}
  ],
  "reasoning": "即使 think 标签未闭合，也要恢复 JSON"
}
"""

    plan = planning_engine._parse_plan(mixed_output)

    assert len(plan.steps) == 2
    assert plan.steps[0].action == "tool"
    assert plan.steps[0].params["tool_name"] == "mock_tool"
    assert plan.reasoning == "即使 think 标签未闭合，也要恢复 JSON"


@pytest.mark.asyncio
async def test_planning_engine_retry_when_truncated_output():
    """测试：首轮输出截断导致 JSON 失败时，规划引擎会自动重试。"""
    first_truncated = _StubInferenceResult(
        content='{"steps":[{"action":"tool","tool_name":"python_executor","params":{"code":"print("',
        finish_reason="length",
    )
    second_valid = _StubInferenceResult(
        content="""
{
  "steps": [
    {"action": "tool", "tool_name": "mock_tool", "params": {"query": "ok"}},
    {"action": "final_answer", "content": "根据执行结果回答用户"}
  ],
  "reasoning": "重试后输出简短可解析计划"
}
""",
        finish_reason="stop",
    )
    llm_hub = _SequenceLLMHub([first_truncated, second_valid])
    planning_engine = PlanningEngine(llm_hub=llm_hub)

    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="You are a test agent",
        agent_config=AgentConfig(planning_model="mock-model"),
    )

    plan = await planning_engine.create_plan(
        agent=agent,
        task="请分析订单并给出洞察",
        available_tools=[MockTool()],
        available_skills=[],
    )

    assert llm_hub.call_count == 2
    assert len(plan.steps) == 2
    assert plan.steps[0].action == "tool"
    assert plan.steps[1].action == "final_answer"
    assert plan.reasoning == "重试后输出简短可解析计划"


@pytest.mark.asyncio
async def test_planning_engine_should_parse_python_literal_payload():
    """规划解析应兼容 Python 风格字面量 dict/list。"""
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    planning_engine = PlanningEngine(llm_hub=inference_engine)

    plan = planning_engine._parse_plan(
        """{
  'steps': [
    {'action': 'tool', 'tool_name': 'mock_tool', 'params': {'query': '郑州教育'}},
    {'action': 'final_answer', 'content': '根据结果回答用户'}
  ],
  'reasoning': '兼容 Python 字面量'
}"""
    )

    assert len(plan.steps) == 2
    assert plan.steps[0].action == "tool"
    assert plan.steps[0].params["tool_name"] == "mock_tool"
    assert plan.reasoning == "兼容 Python 字面量"


@pytest.mark.asyncio
async def test_planning_engine_retry_when_invalid_json_not_truncated():
    """测试：非截断型 JSON 失败时，也会触发一次结构修复重试。"""
    first_invalid = _StubInferenceResult(
        content="""
这里是计划草稿：
{steps:[{action:'tool',tool_name:'mock_tool',params:{query:'郑州教育'}},{action:'final_answer',content:'根据结果回答用户'}],reasoning:'先调用工具'}
""",
        finish_reason="stop",
    )
    second_valid = _StubInferenceResult(
        content="""
{
  "steps": [
    {"action": "tool", "tool_name": "mock_tool", "params": {"query": "郑州教育"}},
    {"action": "final_answer", "content": "根据结果回答用户"}
  ],
  "reasoning": "修复后的严格 JSON 计划"
}
""",
        finish_reason="stop",
    )
    llm_hub = _SequenceLLMHub([first_invalid, second_valid])
    planning_engine = PlanningEngine(llm_hub=llm_hub)

    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="You are a test agent",
        agent_config=AgentConfig(planning_model="mock-model"),
    )

    plan = await planning_engine.create_plan(
        agent=agent,
        task="请搜索郑州教育公众号文章",
        available_tools=[MockTool()],
        available_skills=[],
    )

    assert llm_hub.call_count == 2
    assert len(plan.steps) == 2
    assert plan.steps[0].action == "tool"
    assert plan.steps[1].action == "final_answer"
    assert plan.reasoning == "修复后的严格 JSON 计划"


@pytest.mark.asyncio
async def test_planning_engine_should_block_unauthorized_tool_from_plan():
    """规划阶段应拦截未授权工具，避免把非法计划带到执行阶段。"""
    llm_hub = _SequenceLLMHub(
        [
            _StubInferenceResult(
                """{
  "steps": [
    {"action": "tool", "tool_name": "http_request", "params": {"url": "https://example.com"}},
    {"action": "final_answer", "content": "done"}
  ],
  "reasoning": "尝试直接请求网页"
}"""
            )
        ]
    )
    planning_engine = PlanningEngine(llm_hub=llm_hub)

    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="You are a test agent",
        child_agents=["general_agent"],
        agent_config=AgentConfig(planning_model="mock-model"),
    )

    plan = await planning_engine.create_plan(
        agent=agent,
        task="请抓取一个网页内容",
        available_tools=[MockTool()],
        available_skills=[],
    )

    assert len(plan.steps) == 1
    assert plan.steps[0].action == "final_answer"
    assert plan.reasoning == "计划校验失败"
    assert "不在当前 Agent 授权范围内" in plan.steps[0].params["content"]


@pytest.mark.asyncio
async def test_planning_engine_should_wrap_flattened_tool_args_into_params():
    """规划阶段应把扁平工具参数归一化到 params，兼容直接工具 action 输出。"""
    llm_hub = _SequenceLLMHub(
        [
            _StubInferenceResult(
                """{
  "steps": [
    {
      "action": "mock_tool",
      "query": "华为 Mate 60 Pro 512GB",
      "top_k": 5
    }
  ],
  "reasoning": "直接调用工具"
}"""
            )
        ]
    )
    planning_engine = PlanningEngine(llm_hub=llm_hub)

    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="You are a test agent",
        agent_config=AgentConfig(planning_model="mock-model"),
    )

    plan = await planning_engine.create_plan(
        agent=agent,
        task="测试工具参数归一化",
        available_tools=[MockTool()],
        available_skills=[],
    )

    assert len(plan.steps) == 1
    assert plan.steps[0].action == "tool"
    assert plan.steps[0].params["tool_name"] == "mock_tool"
    assert plan.steps[0].params["params"]["query"] == "华为 Mate 60 Pro 512GB"
    assert plan.steps[0].params["params"]["top_k"] == 5


@pytest.mark.asyncio
async def test_planning_engine_should_convert_tool_written_as_skill():
    """若模型把工具误写成技能，规划公共层应自动归一化为 tool。"""
    llm_hub = _SequenceLLMHub(
        [
            _StubInferenceResult(
                """{
  "steps": [
    {
      "action": "skill",
      "skill_id": "mock_tool",
      "params": {"query": "AI 科技新闻"}
    }
  ],
  "reasoning": "误把工具写成了技能"
}"""
            )
        ]
    )
    planning_engine = PlanningEngine(llm_hub=llm_hub)

    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="You are a test agent",
        agent_config=AgentConfig(planning_model="mock-model"),
    )

    plan = await planning_engine.create_plan(
        agent=agent,
        task="请安装技能",
        available_tools=[MockTool()],
        available_skills=[],
    )

    assert len(plan.steps) == 1
    assert plan.steps[0].action == "tool"
    assert plan.steps[0].params["tool_name"] == "mock_tool"
    assert plan.steps[0].params["params"]["query"] == "AI 科技新闻"


@pytest.mark.asyncio
async def test_planning_engine_should_convert_skill_written_as_tool():
    """若模型把技能误写成工具，规划公共层应自动归一化为 skill。"""
    llm_hub = _SequenceLLMHub(
        [
            _StubInferenceResult(
                """{
  "steps": [
    {
      "action": "tool",
      "tool_name": "find-skills",
      "params": {"query": "AI 科技新闻"}
    }
  ],
  "reasoning": "误把技能写成了工具"
}"""
            )
        ]
    )
    planning_engine = PlanningEngine(llm_hub=llm_hub)

    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="You are a test agent",
        agent_config=AgentConfig(planning_model="mock-model"),
    )

    plan = await planning_engine.create_plan(
        agent=agent,
        task="请搜索技能",
        available_tools=[],
        available_skills=[
            Skill(
                skill_id="find-skills",
                name="Find Skills",
                description="搜索技能",
                prompt_template="Search {query}",
            )
        ],
    )

    assert len(plan.steps) == 1
    assert plan.steps[0].action == "skill"
    assert plan.steps[0].params["skill_id"] == "find-skills"
    assert plan.steps[0].params["params"]["query"] == "AI 科技新闻"


@pytest.mark.asyncio
async def test_planning_engine_should_route_install_target_skill_to_skill_install_tool():
    """待安装目标若被误写成 skill 调用，应改写为 skill_install 工具。"""

    class SkillInstallMockTool(Tool):
        @property
        def name(self) -> str:
            return "skill_install"

        @property
        def schema(self) -> ToolSchema:
            return ToolSchema(
                name="skill_install",
                description="install skill",
                parameters={"type": "object", "properties": {}},
            )

        async def execute(self, params: dict):
            return params

    llm_hub = _SequenceLLMHub(
        [
            _StubInferenceResult(
                """{
  "steps": [
    {
      "action": "skill",
      "skill_id": "newsletter-curation",
      "params": {"source": "inferen-sh/skills@newsletter-curation"}
    }
  ],
  "reasoning": "把待安装目标误写成了 skill"
}"""
            )
        ]
    )
    planning_engine = PlanningEngine(llm_hub=llm_hub)

    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="You are a test agent",
        agent_config=AgentConfig(planning_model="mock-model"),
    )

    plan = await planning_engine.create_plan(
        agent=agent,
        task="请安装 inferen-sh/skills@newsletter-curation",
        available_tools=[SkillInstallMockTool()],
        available_skills=[],
    )

    assert len(plan.steps) == 1
    assert plan.steps[0].action == "tool"
    assert plan.steps[0].params["tool_name"] == "skill_install"
    assert plan.steps[0].params["params"]["package"] == "inferen-sh/skills@newsletter-curation"
    assert plan.steps[0].params["params"]["skill_name"] == "newsletter-curation"
