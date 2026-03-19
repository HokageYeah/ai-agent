"""
测试 Reflection Engine
==================

测试反思引擎的各项功能
"""

import pytest
from app.agents.base import Agent, AgentConfig
from app.agents.execution import ExecutionResult
from app.agents.reflection import ReflectionEngine, ReflectionResult
from app.core.llm_mock import MockLLM
from app.llm_hub.inference import InferenceEngine
from app.llm_hub.registry import ModelRegistry


@pytest.mark.asyncio
async def test_reflection_result_creation():
    """测试创建反思结果"""
    result = ReflectionResult(
        success=True,
        needs_replanning=False,
        feedback="Good job",
        summary="Task completed successfully"
    )
    
    assert result.success is True
    assert result.needs_replanning is False
    assert result.feedback == "Good job"
    
    result_dict = result.to_dict()
    assert result_dict["success"] is True
    assert result_dict["summary"] == "Task completed successfully"


@pytest.mark.asyncio
async def test_reflection_engine_success_scenario():
    """测试成功场景的反思"""
    # 创建 Mock LLM with success response
    mock_response = """```json
{
  "success": true,
  "needs_replanning": false,
  "feedback": "The task was completed successfully",
  "summary": "All steps executed correctly"
}
```"""
    
    mock_llm = MockLLM(responses={}, delay=0.01)
    mock_llm.default_response = mock_response

    
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    reflection_engine = ReflectionEngine(llm_hub=inference_engine)
    
    # 创建测试 Agent
    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role"
    )
    
    # 创建成功的执行结果
    execution_result = ExecutionResult(
        success=True,
        result="Task completed",
        step_results=[{"action": "tool", "success": True}]
    )
    
    # 执行反思
    reflection = await reflection_engine.reflect(
        agent=agent,
        task="Complete a test task",
        execution_result=execution_result
    )
    
    # 验证反思结果
    assert reflection.success is True
    assert reflection.needs_replanning is False
    assert "successfully" in reflection.feedback.lower()


@pytest.mark.asyncio
async def test_reflection_engine_failure_scenario():
    """测试失败场景的反思"""
    # 创建 Mock LLM with failure response
    mock_response = """```json
{
  "success": false,
  "needs_replanning": true,
  "feedback": "The task failed due to an error",
  "summary": "Execution encountered errors"
}
```"""
    
    mock_llm = MockLLM(responses={}, delay=0.01)
    mock_llm.default_response = mock_response

    
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    reflection_engine = ReflectionEngine(llm_hub=inference_engine)
    
    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="Test role"
    )
    
    # 创建失败的执行结果
    execution_result = ExecutionResult(
        success=False,
        result=None,
        step_results=[],
        error="Tool execution failed"
    )
    
    # 执行反思
    reflection = await reflection_engine.reflect(
        agent=agent,
        task="Complete a test task",
        execution_result=execution_result
    )
    
    # 验证反思结果
    assert reflection.success is False
    assert reflection.needs_replanning is True


@pytest.mark.asyncio
async def test_reflection_engine_parse_valid_json():
    """测试解析有效的 JSON 响应"""
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    reflection_engine = ReflectionEngine(llm_hub=inference_engine)
    
    valid_json = """
{
  "success": true,
  "needs_replanning": false,
  "feedback": "Well done",
  "summary": "Task completed"
}
"""
    
    result = reflection_engine._parse_reflection(valid_json)
    
    assert result.success is True
    assert result.needs_replanning is False
    assert result.feedback == "Well done"
    assert result.summary == "Task completed"


@pytest.mark.asyncio
async def test_reflection_engine_parse_invalid_json():
    """测试解析无效的 JSON 响应"""
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    reflection_engine = ReflectionEngine(llm_hub=inference_engine)
    
    invalid_json = "This is not JSON"
    
    result = reflection_engine._parse_reflection(invalid_json)
    
    # 应该返回保守的反思结果
    assert result.success is False
    assert result.needs_replanning is True
    assert "非 JSON" in result.feedback


@pytest.mark.asyncio
async def test_reflection_engine_parse_think_plus_inline_json():
    """测试 `<think>...` + 裸 JSON 的混合输出可被正确解析。"""
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    reflection_engine = ReflectionEngine(llm_hub=inference_engine)

    mixed_output = """
<think>
这里是推理过程
</think>
{
  "success": false,
  "needs_replanning": true,
  "should_continue": true,
  "feedback": "安装失败，需要重试",
  "summary": "skill 安装失败"
}
"""
    result = reflection_engine._parse_reflection(mixed_output)

    assert result.success is False
    assert result.needs_replanning is True
    assert result.should_continue is True
    assert "安装失败" in result.feedback


@pytest.mark.asyncio
async def test_reflection_engine_parse_invalid_json_should_consider_failed_step_results():
    """
    JSON 解析失败时，不应只依赖 execution_result.success。

    当执行结果含失败步骤（step_results.success=False）时，应回退为失败并触发重规划。
    """
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    reflection_engine = ReflectionEngine(llm_hub=inference_engine)

    execution_result = ExecutionResult(
        success=True,  # 流程级成功
        result="final answer",
        step_results=[
            {"action": "tool", "tool_name": "shell_exec", "success": False, "error": "target exists"}
        ],
        error=None,
    )

    result = reflection_engine._parse_reflection("This is not JSON", execution_result=execution_result)

    assert result.success is False
    assert result.needs_replanning is True


@pytest.mark.asyncio
async def test_reflection_engine_build_prompt():
    """测试构建反思 Prompt"""
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    reflection_engine = ReflectionEngine(llm_hub=inference_engine)
    
    execution_result = ExecutionResult(
        success=True,
        result="Completed",
        step_results=[]
    )
    
    prompt = reflection_engine._build_reflection_prompt(
        task="Test task",
        execution_result=execution_result
    )
    
    # 验证 Prompt 包含关键信息
    assert "Test task" in prompt
    assert "成功" in prompt or "Completed" in prompt
    assert "JSON" in prompt
