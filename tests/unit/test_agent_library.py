"""
测试 Agent Library
==================

测试基于 YAML 配置驱动的 Agent 库。
"""

from app.agents.registry import AgentRegistry
from app.agents.library.customer_service import (
    CUSTOMER_SERVICE_MASTER,
    ORDER_AGENT,
    REFUND_AGENT,
    get_all_customer_service_agents,
    register_customer_service_agents,
    load_customer_service_agents,
)


def test_customer_service_master_config():
    """测试客服主 Agent 配置"""
    agent = CUSTOMER_SERVICE_MASTER

    assert agent.agent_id == "cs_master"
    assert agent.name == "客服总监"
    assert "客户服务" in agent.description
    assert len(agent.child_agents) == 3
    assert "order_agent" in agent.child_agents
    assert "refund_agent" in agent.child_agents
    assert "general_agent" in agent.child_agents

    # 验证配置：模型值允许由环境变量注入，不固定写死
    assert isinstance(agent.agent_config.planning_model, str)
    assert agent.agent_config.planning_model
    assert agent.agent_config.max_iterations == 5


def test_order_agent_config():
    """测试订单 Agent 配置"""
    agent = ORDER_AGENT

    assert agent.agent_id == "order_agent"
    assert agent.name == "订单专员"
    assert "订单" in agent.description
    assert len(agent.child_agents) == 1
    assert "general_agent" in agent.child_agents

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
    assert len(agent.child_agents) == 1
    assert "general_agent" in agent.child_agents

    # 验证能力
    assert "退款申请" in agent.capabilities
    assert "退款审核" in agent.capabilities

    # 验证工具
    assert "database_query" in agent.available_tools
    assert "calculator" in agent.available_tools


def test_get_all_customer_service_agents():
    """测试获取所有客服 Agent"""
    agents = get_all_customer_service_agents()

    # 允许未来新增 YAML Agent，至少要包含核心四个
    assert len(agents) >= 4
    assert any(a.agent_id == "cs_master" for a in agents)
    assert any(a.agent_id == "order_agent" for a in agents)
    assert any(a.agent_id == "refund_agent" for a in agents)
    assert any(a.agent_id == "general_agent" for a in agents)


def test_register_customer_service_agents():
    """测试注册所有客服 Agent"""
    registry = AgentRegistry()

    # 初始应该是空的
    assert len(registry.list_agents()) == 0

    # 注册所有客服 Agent
    register_customer_service_agents(registry)

    # 验证注册成功
    assert len(registry.list_agents()) >= 4

    # 验证可以获取每个 Agent
    assert registry.get_agent("cs_master") is not None
    assert registry.get_agent("order_agent") is not None
    assert registry.get_agent("refund_agent") is not None
    assert registry.get_agent("general_agent") is not None


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

    # 订单和退款专员都应该可以继续向 general_agent 移交
    order = registry.get_agent("order_agent")
    refund = registry.get_agent("refund_agent")
    assert "general_agent" in order.child_agents
    assert "general_agent" in refund.child_agents

    # 通用助手是叶子节点
    general = registry.get_agent("general_agent")
    assert len(general.child_agents) == 0


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
    # 主 Agent 只负责委派与沟通，不直接查库
    assert "spawn_agent" in master.available_tools
    assert "database_query" not in master.available_tools

    # 订单 Agent 需要 HTTP 请求（可能用于第三方 API）
    assert "http_request" in order.available_tools

    # 退款 Agent 需要计算器（计算退款金额）
    assert "calculator" in refund.available_tools


def test_load_customer_service_agents_from_yaml():
    """测试从 YAML 文件加载 Agent 配置"""
    agent_map = load_customer_service_agents()
    assert isinstance(agent_map, dict)
    assert "cs_master" in agent_map
    assert "order_agent" in agent_map
    assert "refund_agent" in agent_map
    assert "general_agent" in agent_map


def test_agent_library_import():
    """测试从库中导入 Agent"""
    from app.agents.library import (
        CUSTOMER_SERVICE_MASTER as CSM,
        ORDER_AGENT as OA,
        REFUND_AGENT as RA,
        GENERAL_AGENT as GA,
    )

    assert CSM.agent_id == "cs_master"
    assert OA.agent_id == "order_agent"
    assert RA.agent_id == "refund_agent"
    assert GA.agent_id == "general_agent"
