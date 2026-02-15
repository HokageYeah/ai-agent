"""
测试 Agent Library
==================

测试预定义的 Agent 库
"""

import pytest
from app.agents.base import Agent
from app.agents.registry import AgentRegistry
from app.agents.library.customer_service import (
    CUSTOMER_SERVICE_MASTER,
    ORDER_AGENT,
    REFUND_AGENT,
    get_all_customer_service_agents,
    register_customer_service_agents
)


def test_customer_service_master_config():
    """测试客服主 Agent 配置"""
    agent = CUSTOMER_SERVICE_MASTER
    
    assert agent.agent_id == "cs_master"
    assert agent.name == "客服总监"
    assert "客户服务" in agent.description
    assert len(agent.child_agents) == 2
    assert "order_agent" in agent.child_agents
    assert "refund_agent" in agent.child_agents
    
    # 验证配置
    assert agent.agent_config.planning_model == "gpt-4"
    assert agent.agent_config.max_iterations == 5


def test_order_agent_config():
    """测试订单 Agent 配置"""
    agent = ORDER_AGENT
    
    assert agent.agent_id == "order_agent"
    assert agent.name == "订单专员"
    assert "订单" in agent.description
    assert len(agent.child_agents) == 0  # 没有子 Agent
    
    # 验证能力
    assert "订单查询" in agent.capabilities
    assert "订单更新" in agent.capabilities
    
    # 验证工具
    assert "database_query" in agent.available_tools
    
    # 验证技能
    assert "data_analysis" in agent.available_skills


def test_refund_agent_config():
    """测试退款 Agent 配置"""
    agent = REFUND_AGENT
    
    assert agent.agent_id == "refund_agent"
    assert agent.name == "退款专员"
    assert "退款" in agent.description
    assert len(agent.child_agents) == 0  # 没有子 Agent
    
    # 验证能力
    assert "退款申请" in agent.capabilities
    assert "退款审核" in agent.capabilities
    
    # 验证工具
    assert "database_query" in agent.available_tools
    assert "calculator" in agent.available_tools


def test_get_all_customer_service_agents():
    """测试获取所有客服 Agent"""
    agents = get_all_customer_service_agents()
    
    assert len(agents) == 3
    assert any(a.agent_id == "cs_master" for a in agents)
    assert any(a.agent_id == "order_agent" for a in agents)
    assert any(a.agent_id == "refund_agent" for a in agents)


def test_register_customer_service_agents():
    """测试注册所有客服 Agent"""
    registry = AgentRegistry()
    
    # 初始应该是空的
    assert len(registry.list_agents()) == 0
    
    # 注册所有客服 Agent
    register_customer_service_agents(registry)
    
    # 验证注册成功
    assert len(registry.list_agents()) == 3
    
    # 验证可以获取每个 Agent
    assert registry.get_agent("cs_master") is not None
    assert registry.get_agent("order_agent") is not None
    assert registry.get_agent("refund_agent") is not None


def test_agent_hierarchy():
    """测试 Agent 层次结构"""
    # 创建注册表并注册所有 Agent
    registry = AgentRegistry()
    register_customer_service_agents(registry)
    
    # 获取主 Agent
    master = registry.get_agent("cs_master")
    
    # 验证子 Agent 都存在
    for child_id in master.child_agents:
        child = registry.get_agent(child_id)
        assert child is not None
        # 子 Agent 不应该有子 Agent
        assert len(child.child_agents) == 0


def test_agent_capabilities_integration():
    """测试 Agent 能力的完整性"""
    master = CUSTOMER_SERVICE_MASTER
    order = ORDER_AGENT
    refund = REFUND_AGENT
    
    # 主 Agent 应该有协调能力
    assert "任务委派" in master.capabilities
    
    # 子 Agent 应该有专业能力
    assert "订单查询" in order.capabilities
    assert "退款申请" in refund.capabilities
    
    # 验证工具配置合理
    # 主 Agent 应该有数据库查询能力
    assert "database_query" in master.available_tools
    
    # 订单 Agent 需要 HTTP 请求（可能用于第三方 API）
    assert "http_request" in order.available_tools
    
    # 退款 Agent 需要计算器（计算退款金额）
    assert "calculator" in refund.available_tools


def test_agent_library_import():
    """测试从库中导入 Agent"""
    from app.agents.library import (
        CUSTOMER_SERVICE_MASTER as CSM,
        ORDER_AGENT as OA,
        REFUND_AGENT as RA
    )
    
    assert CSM.agent_id == "cs_master"
    assert OA.agent_id == "order_agent"
    assert RA.agent_id == "refund_agent"
