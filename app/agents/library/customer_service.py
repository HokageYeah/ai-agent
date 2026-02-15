"""
客服系统 Agent 库
================================

本模块定义了客服系统相关的 Agent，包括：
1. CustomerServiceMaster - 客服主 Agent
2. OrderAgent - 订单处理子 Agent
3. RefundAgent - 退款处理子 Agent

作者: AI Agent Team
创建时间: 2026-02-15
"""

from app.agents.base import Agent, AgentConfig


# =============================================================================
# 客服主 Agent
# =============================================================================

CUSTOMER_SERVICE_MASTER = Agent(
    agent_id="cs_master",
    name="客服总监",
    description="负责客户服务的总协调，处理客户问题并委派给专业子 Agent",
    role="你是一个专业的客服总监，负责协调处理各类客户问题。你可以将订单相关问题委派给订单专员，将退款相关问题委派给退款专员。",
    capabilities=["问题分类", "任务委派", "结果整合", "客户沟通"],
    available_tools=["database_query", "datetime"],
    available_skills=["text_writing"],
    child_agents=["order_agent", "refund_agent"],
    agent_config=AgentConfig(
        # 使用默认配置（从环境变量 DEFAULT_MODEL 读取）
        max_iterations=5,
        timeout_seconds=120
    )
)


# =============================================================================
# 订单处理子 Agent
# =============================================================================

ORDER_AGENT = Agent(
    agent_id="order_agent",
    name="订单专员",
    description="专业处理订单相关问题，包括订单查询、订单状态更新、配送跟踪等",
    role="你是一个专业的订单处理专员，负责处理所有订单相关的问题。你可以查询订单信息、更新订单状态、跟踪配送进度。",
    capabilities=["订单查询", "订单更新", "配送跟踪", "订单分析"],
    available_tools=["database_query", "http_request", "datetime"],
    available_skills=["data_analysis"],
    child_agents=[],  # 没有子 Agent
    agent_config=AgentConfig(
        # 使用默认配置（从环境变量 DEFAULT_MODEL 读取）
        max_iterations=3,
        timeout_seconds=60
    )
)


# =============================================================================
# 退款处理子 Agent
# =============================================================================

REFUND_AGENT = Agent(
    agent_id="refund_agent",
    name="退款专员",
    description="专业处理退款相关问题，包括退款申请、退款审核、退款进度查询等",
    role="你是一个专业的退款处理专员，负责处理所有退款相关的问题。你可以处理退款申请、审核退款资格、查询退款进度。",
    capabilities=["退款申请", "退款审核", "退款查询", "退款分析"],
    available_tools=["database_query", "calculator", "datetime"],
    available_skills=["data_analysis"],
    child_agents=[],  # 没有子 Agent
    agent_config=AgentConfig(
        # 使用默认配置（从环境变量 DEFAULT_MODEL 读取）
        max_iterations=3,
        timeout_seconds=60
    )
)


# =============================================================================
# 辅助函数
# =============================================================================

def get_all_customer_service_agents():
    """
    获取所有客服系统 Agent
    
    Returns:
        list[Agent]: Agent 列表
    """
    return [
        CUSTOMER_SERVICE_MASTER,
        ORDER_AGENT,
        REFUND_AGENT
    ]


def register_customer_service_agents(agent_registry):
    """
    将所有客服系统 Agent 注册到 Agent 注册表
    
    Args:
        agent_registry: Agent 注册表实例
    """
    for agent in get_all_customer_service_agents():
        agent_registry.register_agent(agent)
