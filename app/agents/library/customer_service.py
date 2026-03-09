"""
客服系统 Agent 库
================================

本模块定义了客服系统相关的 Agent，包括：
1. CustomerServiceMaster - 客服主 Agent（协调分发）
2. OrderAgent            - 订单处理子 Agent
3. RefundAgent           - 退款处理子 Agent
4. GeneralAssistantAgent - 通用助手子 Agent（处理非订单/退款类问题）

作者: AI Agent Team
创建时间: 2026-02-15
"""

from loguru import logger
from colorama import Fore, Style
from app.agents.base import Agent, AgentConfig, AgentExample


# =============================================================================
# 客服主 Agent
# NOTE: 主 Agent 负责意图识别与委派，自身不直接处理业务，避免职责混乱
# =============================================================================

CUSTOMER_SERVICE_MASTER = Agent(
    agent_id="cs_master",
    name="客服总监",
    description="负责客户服务的总协调，识别用户意图并委派给专业子 Agent 处理",
    role=(
        "你是一个专业的客服总监，负责协调处理各类客户问题。\n"
        "【重要】你只拥有 datetime 工具，没有数据库查询或搜索能力。\n"
        "必须根据以下规则委派给对应子 Agent，禁止自行回答专业性问题：\n"
        "- 订单查询、订单状态、配送跟踪、商品明细 → 委派给 order_agent（订单专员）\n"
        "- 退款申请、退款审核、退款进度 → 委派给 refund_agent（退款专员）\n"
        "- 搜索信息、写代码、翻译、数据分析、文本写作、网络请求、计算、文件处理等通用任务 → 委派给 general_agent（通用助手）\n"
        "- 如果自己没有能力处理，优先委派给 general_agent 尝试处理\n"
        "你的职责是：理解用户问题 → 判断类型 → 委派给合适的子 Agent → 整合结果回复用户。"
    ),
    capabilities=["问题分类", "任务委派", "结果整合", "客户沟通"],
    available_tools=["datetime"],
    available_skills=["text_writing"],
    # NOTE: 更新 child_agents，纳入新增的通用助手 Agent
    child_agents=["order_agent", "refund_agent", "general_agent"],
    agent_config=AgentConfig(
        max_iterations=5,
        timeout_seconds=120
    ),
    # NOTE: 示例任务配置，前端从 API 获取后动态渲染
    examples=[
        AgentExample(
            label="示例1：简单查询",
            content="帮我查询订单号 1002 的详细情况，包括商品、客户和配送状态。"
        ),
        AgentExample(
            label="示例2：复杂查询",
            content="帮我查询客户\"李娜\"的所有订单，并汇总她的总消费金额。"
        ),
        AgentExample(
            label="示例3：子Agent委派",
            content="查询订单号 1002 的详细情况，找到订单的总金额，写入本地",
            style="delegate"
        ),
    ]
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
    child_agents=[],
    agent_config=AgentConfig(
        max_iterations=3,
        timeout_seconds=60
    ),
    # NOTE: 示例任务配置
    examples=[
        AgentExample(
            label="示例1：订单详情",
            content="查询订单号 1002 的详细信息：买了什么商品、支付了多少、现在的配送状态是什么，物流单号是多少？"
        ),
        AgentExample(
            label="示例2：客户订单统计",
            content="查询客户ID为2的所有订单，统计她的订单总数、总金额。"
        ),
        AgentExample(
            label="示例3：订单分析",
            content="分析已发货但未签收的订单，列出订单号、客户。",
            style="delegate"
        ),
    ]
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
    child_agents=[],
    agent_config=AgentConfig(
        max_iterations=3,
        timeout_seconds=60
    ),
    # NOTE: 示例任务配置
    examples=[
        AgentExample(
            label="示例1：退款进度",
            content="查询订单号 1003 的退款进度，请告知当前处理状态和退款金额。"
        ),
        AgentExample(
            label="示例2：待审核退款",
            content="查询所有待审核的退款申请（status=pending），列出申请人。"
        ),
        AgentExample(
            label="示例3：退款统计",
            content="统计所有退款记录的总退款金额，按退款状态分组。",
            style="delegate"
        ),
    ]
)


# =============================================================================
# 通用助手子 Agent
# NOTE: 处理一切非订单/退款类问题，拥有除数据库查询以外的所有工具和全部技能。
#       适合处理的场景包括但不限于：网络搜索、信息查询、代码生成、文本翻译、
#       数据分析、文本写作、HTTP 请求、文件读写、计算器等通用任务。
# =============================================================================

GENERAL_AGENT = Agent(
    agent_id="general_agent",
    name="通用助手",
    description=(
        "处理订单/退款以外的通用请求，包括网络搜索、信息查询、代码生成、"
        "文本翻译、数据分析、文本写作、HTTP 请求、文件读写、计算等各类任务"
    ),
    role=(
        "你是一个能力全面的通用 AI 助手，负责处理用户提出的各类通用问题。\n"
        "【重要工具说明】\n"
        "- search: 搜索网络信息，适合回答「搜一下 X」「查询 X 的最新资讯」等\n"
        "- http_request: 发起 HTTP 请求，适合调用外部 API 或抓取网页内容\n"
        "- python_executor: 执行 Python 代码，适合数据处理、数值计算、验证逻辑\n"
        "- file_read: 读取本地文件内容\n"
        "- file_write: 将内容写入本地文件\n"
        "- calculator: 进行数学计算\n"
        "- datetime: 获取当前日期时间\n"
        "【重要技能说明】\n"
        "- data_analysis: 分析数据并生成报告\n"
        "- code_generation: 根据需求生成代码\n"
        "- text_writing: 撰写文章、报告等文本\n"
        "- translation: 多语言翻译\n"
        "【工作原则】\n"
        "1. 优先选择最合适的工具/技能完成任务\n"
        "2. 如果需要搜索信息，使用 search 工具\n"
        "3. 复杂任务可以组合使用多个工具和技能\n"
        "4. 禁止访问数据库（database_query 工具不可用）\n"
        "5. 给出清晰、准确、有帮助的回答"
    ),
    capabilities=[
        "网络搜索", "信息查询", "代码生成", "文本翻译",
        "数据分析", "文本写作", "HTTP 请求", "文件读写", "数学计算"
    ],
    # NOTE: 囊括除 database_query 之外的所有内置工具
    available_tools=[
        "search",
        "http_request",
        "python_executor",
        "file_read",
        "file_write",
        "calculator",
        "datetime",
    ],
    # NOTE: 挂载全部四个内置技能
    available_skills=[
        "data_analysis",
        "code_generation",
        "text_writing",
        "translation",
    ],
    child_agents=[],  # 通用助手是叶子节点，不再向下委派
    agent_config=AgentConfig(
        # NOTE: 通用任务可能涉及多步骤推理（如搜索+分析+写作），给予更多迭代次数
        max_iterations=8,
        timeout_seconds=180
    ),
    # NOTE: 示例任务配置
    examples=[
        AgentExample(
            label="示例1：中英翻译",
            content="请把这句话翻译成英文：\"人工智能在改变我们的生活。\""
        ),
        AgentExample(
            label="示例2：网络查询",
            content="搜一下什么是 MCP，通俗地解释一下。"
        ),
        AgentExample(
            label="示例3：代码生成",
            content="用 Python 写一个快速排序算法。",
            style="delegate"
        ),
    ]
)

logger.info(
    f"{Fore.GREEN}[客服 Agent 库] 已定义 4 个 Agent："
    f"cs_master / order_agent / refund_agent / general_agent{Style.RESET_ALL}"
)


# =============================================================================
# 辅助函数
# =============================================================================

def get_all_customer_service_agents():
    """
    获取所有客服系统 Agent

    Returns:
        list[Agent]: Agent 列表，顺序为：主 Agent → 各子 Agent
    """
    return [
        CUSTOMER_SERVICE_MASTER,
        ORDER_AGENT,
        REFUND_AGENT,
        GENERAL_AGENT,
    ]


def register_customer_service_agents(agent_registry):
    """
    将所有客服系统 Agent 注册到 Agent 注册表

    Args:
        agent_registry: Agent 注册表实例
    """
    agents = get_all_customer_service_agents()
    for agent in agents:
        agent_registry.register_agent(agent)
        logger.debug(
            f"{Fore.CYAN}[客服 Agent 库] 已注册 Agent: {agent.agent_id} ({agent.name}){Style.RESET_ALL}"
        )
    logger.info(
        f"{Fore.GREEN}[客服 Agent 库] 所有 Agent 注册完成，共 {len(agents)} 个{Style.RESET_ALL}"
    )
