"""
测试 Execution Engine
==================

测试执行引擎的各项功能
"""

from types import SimpleNamespace
from pathlib import Path

import pytest
from app.agents.base import Agent, AgentConfig
from app.agents.planning import Plan, PlanStep
from app.agents.execution import ExecutionEngine, ExecutionResult
from app.llm_hub.tool_gateway import ToolCallingGateway
from app.tools.hub import ToolHub
from app.tools.base import Tool, ToolSchema
from app.tools.builtin.shell import ShellExecutorTool
from app.tools.builtin.skill import SkillInstallTool
from app.skills.base import Skill
from app.skills.manager import SkillManager
from app.core.config import settings
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


class PayloadFailTool(Tool):
    """返回业务失败 payload 的测试工具"""

    @property
    def name(self) -> str:
        return "payload_fail_tool"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="payload_fail_tool",
            description="A payload fail test tool",
            parameters={"type": "object", "properties": {}}
        )

    async def execute(self, params: dict):
        return {"success": False, "error": "业务失败示例"}


class NamedTool(Tool):
    """按名称生成 schema 的通用测试工具"""

    def __init__(self, tool_name: str):
        self._tool_name = tool_name

    @property
    def name(self) -> str:
        return self._tool_name

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self._tool_name,
            description=f"{self._tool_name} test tool",
            parameters={"type": "object", "properties": {}}
        )

    async def execute(self, params: dict):
        return f"{self._tool_name} result"


class EchoParamsTool(Tool):
    """返回收到参数的测试工具"""

    @property
    def name(self) -> str:
        return "echo_params_tool"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="echo_params_tool",
            description="Echo params tool",
            parameters={"type": "object", "properties": {}}
        )

    async def execute(self, params: dict):
        return params


class StubSkillInstaller:
    """
    统一安装服务桩对象。

    设计原因：
    - 当前问题的真实链路是 ExecutionEngine -> ToolCallingGateway ->
      skill_install / shell_exec -> SkillInstallerService；
    - 因此这里需要一个可观测的公共桩，验证“参数是否被兼容层正确收口”，
      而不是只验证某个工具函数的局部返回值。
    """

    def __init__(self):
        self.calls = []
        self.timeout_seconds = 60

    async def install(self, package, skill_name=None, overwrite=False):
        self.calls.append(
            {
                "package": package,
                "skill_name": skill_name,
                "overwrite": overwrite,
            }
        )
        return {
            "success": True,
            "message": "技能已安装到项目工作区",
            "installed_path": f"/tmp/{skill_name or 'auto-skill'}",
        }


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
    skill_manager = SkillManager(auto_discover=False)
    
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
    assert len(result.step_results) == 2
    assert result.step_results[0]["action"] == "tool"
    assert result.step_results[0]["result"] == "tool result"
    assert result.step_results[1]["action"] == "final_answer"


@pytest.mark.asyncio
async def test_execution_engine_should_mark_framework_error_final_answer_as_failed():
    """框架内部错误计划不应被当作成功 final_answer 执行。"""
    tool_hub = ToolHub()
    skill_manager = SkillManager(auto_discover=False)

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

    plan = Plan(
        steps=[
            PlanStep(
                action="final_answer",
                content="当前规划结果不合法，需要重新规划。",
                _framework_error_type="plan_validation_failed",
                _framework_error_message="当前规划结果不合法，需要重新规划。",
                _framework_error_detail="第1步子 Agent 不在当前可委派列表中",
            )
        ],
        reasoning="计划校验失败",
    )

    result = await execution_engine.execute_plan(agent, plan)

    assert result.success is False
    assert result.error is not None
    assert len(result.step_results) == 1
    assert result.step_results[0]["action"] == "final_answer"
    assert result.step_results[0]["success"] is False
    assert result.step_results[0]["_framework_error_type"] == "plan_validation_failed"


@pytest.mark.asyncio
async def test_execution_engine_execute_skill():
    """测试技能执行"""
    # 创建工具中心
    tool_hub = ToolHub()
    
    # 创建技能管理器
    class DummySkillManager:
        def __init__(self, skill):
            self._skill = skill

        def get_skill(self, skill_id):
            if skill_id == self._skill.skill_id:
                return self._skill
            return None

    test_skill = Skill(
        skill_id="test_skill",
        name="Test Skill",
        description="A test skill",
        prompt_template="Execute {task}"
    )
    skill_manager = DummySkillManager(test_skill)
    
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
    skill_manager = SkillManager(auto_discover=False)
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
    assert result.success is False
    assert result.step_results[0]["success"] is False  # 但步骤失败
    assert "不存在" in result.step_results[0]["error"]
    assert "任务未完成" in result.result


@pytest.mark.asyncio
async def test_execution_engine_should_propagate_tool_payload_failure():
    """测试工具 payload 中 success=false 时，步骤应标记失败"""
    tool_hub = ToolHub()
    tool_hub.register_tool(PayloadFailTool())
    skill_manager = SkillManager(auto_discover=False)
    mock_llm = MockLLM()
    mock_llm.default_response = "Task completed"
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

    plan = Plan(
        steps=[
            PlanStep(action="tool", tool_name="payload_fail_tool", params={}),
            PlanStep(action="final_answer", content="Done")
        ]
    )

    result = await execution_engine.execute_plan(agent, plan)

    assert result.success is False
    assert result.step_results[0]["success"] is False
    assert "业务失败示例" in result.step_results[0]["error"]
    assert "任务未完成" in result.result


@pytest.mark.asyncio
async def test_execution_engine_gateway_path_should_normalize_skill_install_aliases():
    """
    经过 ToolCallingGateway 的直调链路，也应兼容安装参数别名漂移。

    覆盖线上真实故障：
    - direct tool call 参数是 `{"source": "...", "skill_id": "..."}`
    - 网关会 skip_validation=True，直接把参数交给工具 execute()
    - 若兼容逻辑只停留在某个局部调用点，就会在真实执行链路里再次报
      “package 不能为空”
    """
    tool_hub = ToolHub()
    installer = StubSkillInstaller()
    skill_install_tool = SkillInstallTool(installer=installer)
    tool_hub.register_tool(skill_install_tool)

    gateway = ToolCallingGateway()
    gateway.register_tool(
        skill_install_tool.name,
        skill_install_tool,
        skill_install_tool.schema.parameters,
    )

    skill_manager = SkillManager(auto_discover=False)
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        llm_hub=inference_engine,
        tool_gateway=gateway,
    )

    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role",
        available_tools=["skill_install"],
    )
    step = PlanStep(
        action="tool",
        tool_name="skill_install",
        params={
            "source": "inferen-sh/skills@newsletter-curation",
            "skill_id": "newsletter-curation",
        },
    )

    result = await execution_engine._execute_tool(step, agent=agent, context={})

    assert result["success"] is True
    assert result["result"]["success"] is True
    assert installer.calls == [
        {
            "package": "inferen-sh/skills@newsletter-curation",
            "skill_name": "newsletter-curation",
            "overwrite": False,
        }
    ]


@pytest.mark.asyncio
async def test_execution_engine_gateway_path_should_proxy_raw_skills_add_to_installer():
    """
    经过 ToolCallingGateway 的 shell_exec 直调链路，也应收口到统一安装服务。

    覆盖线上真实故障：
    - 当模型 fallback 到 `shell_exec("npx skills add ...")`
    - 若没有在 Shell 工具公共层做代理，网关只会看到一个长时间阻塞的命令，
      最终报 `Tool execution timed out (>300.0s)`
    """
    tool_hub = ToolHub()
    installer = StubSkillInstaller()
    shell_tool = ShellExecutorTool(skill_installer=installer)
    tool_hub.register_tool(shell_tool)

    gateway = ToolCallingGateway()
    gateway.register_tool(shell_tool.name, shell_tool, shell_tool.schema.parameters)

    skill_manager = SkillManager(auto_discover=False)
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        llm_hub=inference_engine,
        tool_gateway=gateway,
    )

    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role",
        available_tools=["shell_exec"],
    )
    step = PlanStep(
        action="tool",
        tool_name="shell_exec",
        params={
            "command": "npx skills add inferen-sh/skills@newsletter-curation 2>&1 || echo 'INSTALL_FAILED'",
        },
    )

    result = await execution_engine._execute_tool(step, agent=agent, context={})

    assert result["success"] is True
    assert result["result"]["success"] is True
    assert result["result"]["proxied_to_skill_install"] is True
    assert installer.calls == [
        {
            "package": "inferen-sh/skills@newsletter-curation",
            "skill_name": None,
            "overwrite": False,
        }
    ]


@pytest.mark.asyncio
async def test_execution_engine_should_not_expose_success_template_after_failed_step():
    """当前序步骤失败时，final_answer 不应继续输出规划里的成功模板。"""
    tool_hub = ToolHub()
    tool_hub.register_tool(PayloadFailTool())
    skill_manager = SkillManager(auto_discover=False)
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

    plan = Plan(
        steps=[
            PlanStep(action="tool", tool_name="payload_fail_tool", params={}),
            PlanStep(action="final_answer", content="已成功安装目标技能"),
        ]
    )

    result = await execution_engine.execute_plan(agent, plan)

    assert result.success is False
    assert result.result != "已成功安装目标技能"
    assert "payload_fail_tool" in result.result
    assert "业务失败示例" in result.result
    assert result.step_results[1]["result"] == result.result


@pytest.mark.asyncio
async def test_execution_engine_should_write_real_final_answer_back_to_step_result(monkeypatch):
    """final_answer 步骤完成后，应把真实合成结果回写到步骤结果中。"""
    tool_hub = ToolHub()
    tool_hub.register_tool(TestTool())
    skill_manager = SkillManager(auto_discover=False)
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)

    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        llm_hub=inference_engine
    )

    async def fake_synthesize_answer(*args, **kwargs):
        return "这是合成后的真实最终答案"

    monkeypatch.setattr(execution_engine, "_synthesize_answer", fake_synthesize_answer)

    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role"
    )
    plan = Plan(
        steps=[
            PlanStep(action="tool", tool_name="test_tool", params={}),
            PlanStep(action="final_answer", content="根据以上结果回答用户"),
        ]
    )

    result = await execution_engine.execute_plan(agent, plan)

    assert result.result == "这是合成后的真实最终答案"
    assert result.step_results[1]["action"] == "final_answer"
    assert result.step_results[1]["result"] == "这是合成后的真实最终答案"
    assert result.step_results[1]["template"] == "根据以上结果回答用户"


@pytest.mark.asyncio
async def test_execution_engine_should_skip_llm_synthesis_for_single_delegate_result(monkeypatch):
    """单一委派结果应直接走确定性 Markdown 收口，避免额外触发一次 LLM 合成。"""
    tool_hub = ToolHub()
    skill_manager = SkillManager(auto_discover=False)
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)

    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        llm_hub=inference_engine,
    )

    async def fake_delegate(*args, **kwargs):
        return {
            "success": True,
            "action": "delegate",
            "agent_id": "general_agent",
            "result": "【skill】\n搜索关键词：新闻, news\n\n1. newsletter-curation\n2. hackernews",
        }

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("单一委派结果不应再触发 LLM 合成")

    monkeypatch.setattr(execution_engine, "_delegate_to_agent", fake_delegate)
    monkeypatch.setattr(execution_engine, "_synthesize_answer", fail_if_called)

    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role",
    )
    plan = Plan(
        steps=[
            PlanStep(action="delegate", agent_id="general_agent", params={"task": "查询新闻技能"}),
            PlanStep(action="final_answer", content="根据以上结果回答用户"),
        ]
    )

    result = await execution_engine.execute_plan(agent, plan, context={"task": "使用find-skills技能查询 新闻技能"})

    assert result.success is True
    assert result.result.startswith("# 执行结果")
    assert "## skill" in result.result
    assert "newsletter-curation" in result.result
    assert result.step_results[1]["result"] == result.result


@pytest.mark.asyncio
async def test_execution_engine_should_fallback_to_markdown_when_synthesis_fails(monkeypatch):
    """多步骤结果在合成失败时，应统一降级为标准 Markdown，而不是原始拼接文本。"""
    tool_hub = ToolHub()
    tool_hub.register_tool(TestTool())
    tool_hub.register_tool(NamedTool("second_tool"))
    skill_manager = SkillManager(auto_discover=False)
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)

    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        llm_hub=inference_engine,
    )

    async def fake_infer(*args, **kwargs):
        raise ValueError("API 返回错误，无法获取回复内容")

    monkeypatch.setattr(execution_engine.llm_hub, "infer", fake_infer)

    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role",
    )
    plan = Plan(
        steps=[
            PlanStep(action="tool", tool_name="test_tool", params={}),
            PlanStep(action="tool", tool_name="second_tool", params={}),
            PlanStep(action="final_answer", content="根据以上结果回答用户"),
        ]
    )

    result = await execution_engine.execute_plan(agent, plan, context={"task": "测试 Markdown 降级"})

    assert result.success is True
    assert result.result.startswith("# 执行结果")
    assert "## 说明" in result.result
    assert "## test_tool" in result.result
    assert "## second_tool" in result.result
    assert "【tool】" not in result.result
    assert result.step_results[-1]["result"] == result.result


@pytest.mark.asyncio
async def test_execution_engine_empty_plan():
    """测试执行空计划"""
    tool_hub = ToolHub()
    skill_manager = SkillManager(auto_discover=False)
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


@pytest.mark.asyncio
async def test_resolve_step_placeholders_supports_dotted_last_tool_result():
    """测试占位符解析支持点路径（如 {{last_tool_result.content}}）"""
    tool_hub = ToolHub()
    skill_manager = SkillManager(auto_discover=False)
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)

    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        llm_hub=inference_engine
    )

    step = PlanStep(
        action="tool",
        tool_name="archive_extract",
        params={
            "archive_path": "{{last_tool_result.content}}",
            "output_dir": "app/skills/skills_md/find-skills"
        }
    )
    prev_results = [
        {
            "success": True,
            "action": "tool",
            "tool_name": "http_request",
            "result": {
                "content": "/tmp/find-skills.zip",
                "status_code": 200
            }
        }
    ]

    resolved = execution_engine._resolve_step_placeholders(step, prev_results)

    assert step.params["params"]["archive_path"] == "{{last_tool_result.content}}"
    assert resolved.params["params"]["archive_path"] == "/tmp/find-skills.zip"


@pytest.mark.asyncio
async def test_resolve_step_placeholders_should_use_delegate_result_as_last_tool_result():
    """测试委派结果也可作为 {{last_tool_result}} 的占位符来源。"""
    tool_hub = ToolHub()
    skill_manager = SkillManager(auto_discover=False)
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)

    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        llm_hub=inference_engine
    )

    step = PlanStep(
        action="skill",
        skill_id="wechat-article-search",
        params={
            "keyword": "{{last_tool_result}}",
        }
    )
    prev_results = [
        {
            "success": True,
            "action": "delegate",
            "agent_id": "order_agent",
            "result": {
                "success": True,
                "result": "华为 Mate 60 Pro 512GB",
                "step_results": [],
                "error": None,
            },
        }
    ]

    resolved = execution_engine._resolve_step_placeholders(step, prev_results)

    assert resolved.params["params"]["keyword"] == "华为 Mate 60 Pro 512GB"


def test_normalize_skill_output_params_should_avoid_unrequested_persistence_and_rewrite_requested_output():
    """未明确要求保存时应移除 output；明确要求保存时相对路径应改写到运行产物目录。"""
    tool_hub = ToolHub()
    skill_manager = SkillManager(auto_discover=False)
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)

    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        llm_hub=inference_engine
    )

    runtime_dir = Path("/tmp/wechat-runtime-test")

    removed = execution_engine._normalize_skill_output_params(
        params={"query": "郑州发布 教育", "output": "zz_education_articles.json"},
        runtime_dir=runtime_dir,
        task="搜索郑州发布微信公众号教育相关文章给我",
        skill_id="wechat-article-search",
    )
    assert "output" not in removed

    rewritten = execution_engine._normalize_skill_output_params(
        params={"query": "郑州发布 教育", "output": "zz_education_articles.json"},
        runtime_dir=runtime_dir,
        task="搜索后请保存成 json 文件",
        skill_id="wechat-article-search",
    )
    assert rewritten["output"] == str((runtime_dir / "zz_education_articles.json").resolve())


def test_normalize_tool_runtime_params_should_rewrite_workspace_and_reuse_download_path(
    tmp_path,
    monkeypatch,
):
    """安装 fallback 链路应统一改写工作区路径，并复用上一跳下载的真实 ZIP 路径。"""
    tool_hub = ToolHub()
    skill_manager = SkillManager(auto_discover=False)
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        llm_hub=inference_engine,
    )

    workspace_dir = tmp_path / "skills_md"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    download_zip = tmp_path / "http_request_result.zip"
    download_zip.write_bytes(b"zip")
    monkeypatch.setattr(settings, "AGENT_WORKSPACE_DIR", str(workspace_dir))

    normalized_archive = execution_engine._normalize_tool_runtime_params(
        tool_name="archive_extract",
        params={
            "archive_path": "/tmp/claude-meta-skill-main.zip",
            "target_path": "/tmp/claude-meta-skill-extracted",
        },
        prev_results=[
            {
                "success": True,
                "action": "tool",
                "tool_name": "http_request",
                "result": {
                    "is_binary": True,
                    "download_path": str(download_zip),
                    "content": str(download_zip),
                },
            }
        ],
    )
    assert normalized_archive["archive_path"] == str(download_zip)
    assert normalized_archive["target_path"] == "/tmp/claude-meta-skill-extracted"

    normalized_file = execution_engine._normalize_tool_runtime_params(
        tool_name="file_read",
        params={"path": "/app/skills/skills_md/daily-ai-news/SKILL.md"},
        prev_results=[],
    )
    assert normalized_file["path"] == str((workspace_dir / "daily-ai-news" / "SKILL.md").resolve())

    normalized_shell = execution_engine._normalize_tool_runtime_params(
        tool_name="shell_exec",
        params={
            "command": "cp /tmp/a.zip /app/skills/skills_md/daily-ai-news/archive.zip"
        },
        prev_results=[],
    )
    assert str(workspace_dir / "daily-ai-news" / "archive.zip") in normalized_shell["command"]


def test_normalize_tool_runtime_params_should_not_duplicate_existing_absolute_workspace_path(
    tmp_path,
    monkeypatch,
):
    """真实绝对工作区路径不应再次被拼接，避免出现 `/workspace/.../workspace/...` 双路径。"""
    tool_hub = ToolHub()
    skill_manager = SkillManager(auto_discover=False)
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        llm_hub=inference_engine,
    )

    workspace_dir = (tmp_path / "app" / "skills" / "skills_md").resolve()
    workspace_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "AGENT_WORKSPACE_DIR", str(workspace_dir))

    existing_skill_path = str((workspace_dir / "daily-ai-news" / "SKILL.md").resolve())
    normalized_file = execution_engine._normalize_tool_runtime_params(
        tool_name="file_read",
        params={"path": existing_skill_path},
        prev_results=[],
    )
    assert normalized_file["path"] == existing_skill_path

    existing_shell_command = (
        f"mkdir -p {workspace_dir / 'daily-ai-news'} "
        f"&& cp -r /tmp/skills_install/claude-meta-skill-main/daily-ai-news/* "
        f"{workspace_dir / 'daily-ai-news'}/"
    )
    normalized_shell = execution_engine._normalize_tool_runtime_params(
        tool_name="shell_exec",
        params={"command": existing_shell_command},
        prev_results=[],
    )
    assert normalized_shell["command"] == existing_shell_command


@pytest.mark.asyncio
async def test_execute_skill_should_infer_script_tool_constraints_from_metadata():
    """脚本型技能未声明工具时，应收敛到 shell_exec 相关工具而非开放整套 Agent 工具。"""
    tool_hub = ToolHub()
    for tool_name in ("shell_exec", "file_read", "list_dir", "browser", "skill_install"):
        tool_hub.register_tool(NamedTool(tool_name))

    class DummySkillManager:
        def __init__(self, skill):
            self._skill = skill

        def get_skill(self, skill_id):
            if skill_id == self._skill.skill_id:
                return self._skill
            return None

    class CaptureLLMHub:
        def __init__(self):
            self.last_messages = None
            self.last_config = None

        async def infer(self, messages, config):
            self.last_messages = messages
            self.last_config = config
            return SimpleNamespace(content="搜索成功")

    test_skill = Skill(
        skill_id="script_skill",
        name="Script Skill",
        description="依赖脚本执行的技能",
        prompt_template="请搜索 {query}",
        scripts=["scripts/search_wechat.js"],
    )
    skill_manager = DummySkillManager(test_skill)
    llm_hub = CaptureLLMHub()

    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        llm_hub=llm_hub
    )

    agent = Agent(
        agent_id="general_agent",
        name="General Agent",
        description="General test agent",
        role="Test role",
        available_tools=["shell_exec", "file_read", "list_dir", "browser", "skill_install"],
        agent_config=AgentConfig(execution_model="mock-model"),
    )

    result = await execution_engine._execute_skill(
        step=PlanStep(
            action="skill",
            skill_id="script_skill",
            params={"query": "华为 Mate 60 Pro"},
        ),
        context={"task": "搜索公众号文章"},
        agent=agent,
        prev_results=[],
    )

    tool_names = [
        execution_engine._extract_tool_name_from_schema(schema)
        for schema in (llm_hub.last_config.tools or [])
    ]

    assert result["success"] is True
    assert set(tool_names) == {"shell_exec", "file_read", "list_dir"}
    assert "browser" not in tool_names
    assert "skill_install" not in tool_names


@pytest.mark.asyncio
async def test_execute_tool_should_support_flattened_step_params():
    """执行阶段应兼容扁平参数写法，避免工具收到空参数。"""
    tool_hub = ToolHub()
    tool_hub.register_tool(EchoParamsTool())
    skill_manager = SkillManager(auto_discover=False)
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)

    execution_engine = ExecutionEngine(
        tool_hub=tool_hub,
        skill_manager=skill_manager,
        llm_hub=inference_engine
    )

    result = await execution_engine._execute_tool(
        step=PlanStep(
            action="tool",
            tool_name="echo_params_tool",
            content="进度通知",
            message_type="progress",
        )
    )

    assert result["success"] is True
    assert result["result"]["content"] == "进度通知"
    assert result["result"]["message_type"] == "progress"
