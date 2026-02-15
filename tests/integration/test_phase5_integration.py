"""
阶段五集成测试
==============

测试 LangGraph Agent Executor、Chat Service、Automation Service 的集成
"""

import pytest
from app.services.chat_service import ChatService
from app.services.automation_service import AutomationService
from app.agents.langgraph_executor import LangGraphAgentExecutor
from app.agents.base import Agent
from app.core.llm_mock import MockLLM
from app.llm_hub.inference import InferenceEngine
from app.llm_hub.registry import ModelRegistry
from app.tools.hub import ToolHub
from app.skills.manager import SkillManager
from app.tools.builtin.calculator import CalculatorTool
from app.memory.short_term import ShortTermMemory

@pytest.fixture
def mock_llm():
    """创建 Mock LLM"""
    llm = MockLLM()
    # 设置默认响应
    llm.default_response = "I am a mock LLM"
    return llm

@pytest.fixture
def inference_engine(mock_llm):
    """创建推理引擎"""
    registry = ModelRegistry()
    return InferenceEngine(provider=mock_llm, model_registry=registry)

@pytest.fixture
def tool_hub():
    """创建工具中心"""
    hub = ToolHub()
    hub.register_tool(CalculatorTool())
    return hub

@pytest.fixture
def skill_manager():
    """创建技能管理器"""
    # 暂时不添加技能
    return SkillManager()

@pytest.mark.asyncio
async def test_chat_service_integration(inference_engine, mock_llm):
    """测试 Chat Service 集成"""
    memory = ShortTermMemory()
    service = ChatService(llm_hub=inference_engine, memory=memory)
    
    # 模拟多轮对话
    mock_llm.responses = {
        "hello": "Hello! How can I help you?",
        "memory_check": "I remember you said hello."
    }
    
    # 第一轮
    resp1 = await service.chat(
        conversation_id="integration_test_1",
        message="hello"
    )
    assert resp1["message"] == "Hello! How can I help you?"
    
    # 第二轮
    resp2 = await service.chat(
        conversation_id="integration_test_1",
        message="memory_check"
    )
    assert resp2["message"] == "I remember you said hello."
    
    # 验证记忆
    history = service.get_conversation_history("integration_test_1")
    assert len(history) == 4  # 2 user + 2 assistant

@pytest.mark.asyncio
async def test_automation_service_integration(inference_engine, mock_llm, tool_hub):
    """测试 Automation Service 集成"""
    service = AutomationService(llm_hub=inference_engine, tool_hub=tool_hub)
    
    # 模拟代码生成
    mock_llm.default_response = "```python\nprint('hello')\n```"
    
    result = await service.code_generation(
        requirements="print hello",
        language="python"
    )
    assert result["success"] is True
    assert "print('hello')" in result["code"]

@pytest.mark.asyncio
async def test_langgraph_executor_integration(inference_engine, tool_hub, skill_manager):
    """测试 LangGraph Executor 集成"""
    executor = LangGraphAgentExecutor(
        llm_hub=inference_engine,
        tool_hub=tool_hub,
        skill_manager=skill_manager
    )
    
    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="Integration Test Agent",
        role="Tester"
    )
    
    # 模拟复杂的执行流程
    # 1. 规划: 使用计算器
    # 2. 执行: 调用计算器
    # 3. 反思: 成功
    
    # 规划阶段响应
    plan_response = """```json
    {
      "steps": [
        {"action": "tool", "tool_name": "calculator", "params": {"expression": "1+1"}},
        {"action": "final_answer", "content": "2"}
      ],
      "reasoning": "Simple calculation"
    }
    ```"""
    
    # 反思阶段响应
    reflect_response = """```json
    {
      "success": true,
      "needs_replanning": false,
      "feedback": "Good job",
      "summary": "Task completed"
    }
    ```"""
    
    async def dynamic_chat(messages, **kwargs):
        content = messages[-1]["content"]
        if "请制定详细的执行计划" in content:
            return {"role": "assistant", "content": plan_response}
        elif "请评估" in content:
            return {"role": "assistant", "content": reflect_response}
        else:
            return {"role": "assistant", "content": "I don't know"}
            
    # 自定义 Mock Provider
    from app.llm_hub.providers.base import LLMProvider
    
    class SmartMockProvider(LLMProvider):
        async def chat(self, messages, config):
            return await dynamic_chat(messages)
        
        async def stream(self, messages, config):
            yield {"content": "stream"}
            
        async def embeddings(self, texts, model):
            return [[0.1]*1536] * len(texts)
            
    # 使用 set_provider 替换默认供应商
    inference_engine.set_provider(SmartMockProvider())
    
    result = await executor.execute(
        agent=agent,
        task="Calculate 1+1"
    )
    
    assert result["success"] is True
    assert result["result"]["result"] == "2"
    assert len(result["messages"]) > 0

