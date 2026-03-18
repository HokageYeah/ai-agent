import pytest
from app.core.config import get_default_model
from app.agents.base import Agent, AgentConfig

def test_agent_config_defaults():
    """测试 AgentConfig 默认值"""
    config = AgentConfig()
    assert config.planning_model == get_default_model("openai")
    assert config.max_iterations == 10

def test_agent_model_creation():
    """测试 Agent 模型创建"""
    agent = Agent(
        agent_id="test_agent",
        name="Test Agent",
        description="A test agent",
        role="You are a test agent."
    )
    
    assert agent.agent_id == "test_agent"
    assert agent.agent_config.execution_model == get_default_model("openai")
    assert len(agent.available_tools) == 0

def test_agent_custom_config():
    """测试自定义配置"""
    custom_config = AgentConfig(planning_model="claude-3-opus", max_iterations=5)
    agent = Agent(
        agent_id="advanced_agent",
        name="Advanced Agent",
        description="...",
        role="...",
        agent_config=custom_config
    )
    
    assert agent.agent_config.planning_model == "claude-3-opus"
    assert agent.agent_config.max_iterations == 5
