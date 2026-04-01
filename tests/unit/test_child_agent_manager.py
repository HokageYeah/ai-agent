"""
测试 Child Agent Manager
==================

测试子 Agent 管理器的各项功能
"""

import pytest
from app.agents.base import Agent, AgentConfig
from app.agents.registry import AgentRegistry
from app.agents.child_agent_manager import ChildAgentManager
from app.tools.hub import ToolHub
from app.skills.manager import SkillManager
from app.core.llm_mock import MockLLM
from app.llm_hub.inference import InferenceEngine
from app.llm_hub.registry import ModelRegistry


@pytest.mark.asyncio
async def test_child_agent_manager_creation():
    """测试创建子 Agent 管理器"""
    agent_registry = AgentRegistry()
    tool_hub = ToolHub()
    skill_manager = SkillManager()
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    manager = ChildAgentManager(
        agent_registry=agent_registry,
        llm_hub=inference_engine,
        tool_hub=tool_hub,
        skill_manager=skill_manager
    )
    
    assert manager is not None
    assert len(manager._call_stack) == 0


@pytest.mark.asyncio
async def test_child_agent_manager_delegate_nonexistent_agent():
    """测试委派给不存在的子 Agent"""
    agent_registry = AgentRegistry()
    tool_hub = ToolHub()
    skill_manager = SkillManager()
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    manager = ChildAgentManager(
        agent_registry=agent_registry,
        llm_hub=inference_engine,
        tool_hub=tool_hub,
        skill_manager=skill_manager
    )
    
    # 委派给不存在的 Agent
    result = await manager.delegate_task(
        parent_agent_id="parent",
        child_agent_id="nonexistent",
        task="Test task"
    )
    
    # 验证结果
    assert result["success"] is False
    assert "不存在" in result["error"]


@pytest.mark.asyncio
async def test_child_agent_manager_delegate_success():
    """测试成功的子 Agent 委派"""
    # 创建 Agent 注册表
    agent_registry = AgentRegistry()
    
    # 注册测试 Agent
    child_agent = Agent(
        agent_id="child_agent",
        name="Child Agent",
        description="A child agent",
        role="Child role"
    )
    agent_registry.register_agent(child_agent)
    
    # 创建其他组件
    tool_hub = ToolHub()
    skill_manager = SkillManager()
    
    # 创建 Mock LLM with proper responses
    mock_response = """```json
{
  "steps": [
    {"action": "final_answer", "content": "Child agent completed the task"}
  ],
  "reasoning": "Simple task completion"
}
```"""
    
    mock_llm = MockLLM(responses={}, delay=0.01)
    mock_llm.default_response = mock_response

    
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    manager = ChildAgentManager(
        agent_registry=agent_registry,
        llm_hub=inference_engine,
        tool_hub=tool_hub,
        skill_manager=skill_manager
    )
    
    # 委派任务
    result = await manager.delegate_task(
        parent_agent_id="parent",
        child_agent_id="child_agent",
        task="Complete a simple task"
    )
    
    # 验证结果
    assert result["success"] is True
    assert result["agent_id"] == "child_agent"
    assert result["agent_name"] == "Child Agent"


@pytest.mark.asyncio
async def test_child_agent_manager_circular_dependency():
    """测试循环依赖检查"""
    agent_registry = AgentRegistry()
    tool_hub = ToolHub()
    skill_manager = SkillManager()
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    manager = ChildAgentManager(
        agent_registry=agent_registry,
        llm_hub=inference_engine,
        tool_hub=tool_hub,
        skill_manager=skill_manager
    )
    
    # 注册测试 Agent
    agent = Agent(
        agent_id="agent1",
        name="Agent 1",
        description="Test agent",
        role="Test role"
    )
    agent_registry.register_agent(agent)
    
    # 手动添加到调用链模拟循环
    manager._call_stack.add("agent1")
    
    # 尝试再次委派给相同的 Agent
    result = await manager.delegate_task(
        parent_agent_id="parent",
        child_agent_id="agent1",
        task="Test task"
    )
    
    # 验证结果
    assert result["success"] is False
    assert "循环依赖" in result["error"]


@pytest.mark.asyncio
async def test_child_agent_manager_clear_call_stack():
    """测试清空调用链"""
    agent_registry = AgentRegistry()
    tool_hub = ToolHub()
    skill_manager = SkillManager()
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    manager = ChildAgentManager(
        agent_registry=agent_registry,
        llm_hub=inference_engine,
        tool_hub=tool_hub,
        skill_manager=skill_manager
    )
    
    # 添加一些元素到调用链
    manager._call_stack.add("agent1")
    manager._call_stack.add("agent2")
    
    assert len(manager._call_stack) == 2
    
    # 清空调用链
    manager.clear_call_stack()
    
    assert len(manager._call_stack) == 0


@pytest.mark.asyncio
async def test_child_agent_manager_check_circular_dependency():
    """测试循环依赖检查方法"""
    agent_registry = AgentRegistry()
    
    # 创建层次结构: parent -> child1 -> grandchild
    parent = Agent(
        agent_id="parent",
        name="Parent",
        description="Parent agent",
        role="Parent",
        child_agents=["child1"]
    )
    
    child1 = Agent(
        agent_id="child1",
        name="Child 1",
        description="Child agent",
        role="Child",
        child_agents=["grandchild"]
    )
    
    grandchild = Agent(
        agent_id="grandchild",
        name="Grandchild",
        description="Grandchild agent",
        role="Grandchild",
        child_agents=[]
    )
    
    agent_registry.register_agent(parent)
    agent_registry.register_agent(child1)
    agent_registry.register_agent(grandchild)
    
    tool_hub = ToolHub()
    skill_manager = SkillManager()
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    manager = ChildAgentManager(
        agent_registry=agent_registry,
        llm_hub=inference_engine,
        tool_hub=tool_hub,
        skill_manager=skill_manager
    )
    
    # 检查是否存在循环依赖
    # parent -> child1: 应该没有循环
    assert not manager._check_circular_dependency("parent", "child1")
    
    # parent -> grandchild: 应该没有循环
    assert not manager._check_circular_dependency("parent", "grandchild")
    
    # parent -> parent: 应该有循环
    assert manager._check_circular_dependency("parent", "parent")


@pytest.mark.asyncio
async def test_child_agent_manager_should_forward_conversation_context_to_sub_agent(monkeypatch):
    """委派子 Agent 时，应透传 conversation_id 与上游筛选后的上下文。"""
    from app.agents import langgraph_executor as executor_module

    agent_registry = AgentRegistry()
    child_agent = Agent(
        agent_id="order_agent",
        name="订单助手",
        description="订单相关查询",
        role="订单处理",
    )
    agent_registry.register_agent(child_agent)

    tool_hub = ToolHub()
    skill_manager = SkillManager()
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)

    manager = ChildAgentManager(
        agent_registry=agent_registry,
        llm_hub=inference_engine,
        tool_hub=tool_hub,
        skill_manager=skill_manager
    )

    captured = {}

    async def fake_execute_with_callback(
        self,
        agent,
        task,
        stream_callback,
        conversation_id=None,
        conversation_history=None,
        conversation_turn_id=None,
        source_user_task=None,
        execution_scope="subtask",
        extra_context_messages=None,
        user_rejected_tools=None,
    ):
        captured["agent_id"] = agent.agent_id
        captured["task"] = task
        captured["conversation_id"] = conversation_id
        captured["conversation_history"] = conversation_history
        captured["conversation_turn_id"] = conversation_turn_id
        captured["source_user_task"] = source_user_task
        captured["execution_scope"] = execution_scope
        captured["extra_context_messages"] = extra_context_messages
        captured["user_rejected_tools"] = user_rejected_tools
        return {
            "success": True,
            "result": {
                "success": True,
                "result": "历史上下文已透传",
                "step_results": [],
                "error": None,
            },
            "error": None,
            "user_rejected_tools": user_rejected_tools or [],
            "iterations": 1,
        }

    monkeypatch.setattr(
        executor_module.LangGraphAgentExecutor,
        "execute_with_callback",
        fake_execute_with_callback,
    )

    extra_context_messages = [
        {
            "role": "user",
            "content": "【历史任务摘要】\n任务: 订单1002的商品是谁买的\n结果: ✅ 成功\n结论: 买家是李娜",
        }
    ]

    result = await manager.delegate_task(
        parent_agent_id="cs_master",
        child_agent_id="order_agent",
        task="查询订单1002的买家信息",
        conversation_id="conv-order-repeat",
        extra_context_messages=extra_context_messages,
        stream_callback=lambda event: None,
        user_rejected_tools=["file_write"],
    )

    assert result["success"] is True
    assert captured["agent_id"] == "order_agent"
    assert captured["conversation_id"] == "conv-order-repeat"
    assert captured["execution_scope"] == "subtask"
    assert captured["extra_context_messages"] == extra_context_messages
    assert captured["user_rejected_tools"] == ["file_write"]
