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
        "【重要】你只拥有 datetime 和 spawn_agent 工具，没有数据库查询或搜索能力。\n"
        "\n"
        "【spawn_agent 工具说明】使用 spawn_agent 工具将任务委派给子 Agent 执行，\n"
        "  - agent_id: 指定要委派的子 Agent（order_agent / refund_agent / general_agent）\n"
        "  - task: 清晰描述子 Agent 需要完成的任务（务必包含足够上下文信息）\n"
        "\n"
        "【任务委派分类规则】\n"
        "- 订单查询、订单状态、配送跟踪、商品明细等订单相关问题 → spawn_agent(agent_id='order_agent')\n"
        "- 退款申请、退款审核、退款进度等退款相关问题 → spawn_agent(agent_id='refund_agent')\n"
        "- 搜索信息、写代码、翻译、数据分析、文本写作、网络请求、计算、文件处理等通用任务 → spawn_agent(agent_id='general_agent')\n"
        "- 如果自己没有能力处理，优先 spawn_agent 委派给 general_agent 尝试处理\n"
        "\n"
        "【⚠️ 关键规范：委派任务必须完整，禁止省略用户需求】\n"
        "委派给子 Agent 的 task 字段必须包含用户原始需求的**所有内容**，包括附加操作（如'写入本地'、'保存文件'、'生成报表'等）。\n"
        "禁止在委派描述中省略任何用户需求，否则子 Agent 不知道还有后续操作要完成。\n"
        "举例：用户说'查询订单1002并写入本地'，委派给 order_agent 的 task 应该是：\n"
        "  '查询订单号1002的详细情况，包括商品、客户、配送状态，查询完成后将结果写入本地文件。"
        "（order_agent 会在查询完成后通过 spawn_agent 将数据和文件写入任务转交给 general_agent）'\n"
        "\n"
        "【说明】order_agent / refund_agent 遇到自身工具解决不了的问题时（如文件写入、搜索、代码执行等），\n"
        "会自动将任务连同已查到的数据一起移交给 general_agent 继续处理，无需你干预，\n"
        "但前提是：你委派时的 task 描述中必须包含这些附加需求！\n"
        "\n"
        "你的职责是：理解用户问题 → 判断类型 → 调用 spawn_agent 委派给合适的子 Agent（携带完整需求）→ 整合结果回复用户。"
    ),
    capabilities=["问题分类", "任务委派", "结果整合", "客户沟通"],
    available_tools=["datetime", "spawn_agent"],
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
    role=(
        "你是一个专业的订单处理专员，负责处理所有订单相关的问题。\n"
        "【工具说明】\n"
        "- database_query: 执行预置的标准订单查询（按订单号、客户ID、配送状态等常规条件）\n"
        "- http_request: 调用外部物流 / 支付 API\n"
        "- datetime: 获取当前时间\n"
        "- spawn_agent: 将无法处理的任务转交给 general_agent（文件写入、搜索、代码执行等通用操作）\n"
        "\n"
        "【工作流程】\n"
        "第一步：优先使用 database_query 和 http_request 处理任务中的订单查询部分。\n"
        "第二步：任务完成后，检查用户的完整需求——如果还有自己工具覆盖不到的需求，\n"
        "        必须通过 spawn_agent 将任务连同已查到的数据一起转交给 general_agent 处理。\n"
        "\n"
        "【⚠️ 必须通过 spawn_agent 转交给 general_agent 的典型场景（禁止自行宣告完成）】\n"
        "- 写入本地文件 / 保存文件 / 生成文件（file_write）\n"
        "- 按商品名反查购买人、多表关联统计、复杂聚合分析等预置接口不支持的 SQL\n"
        "- 生成 Excel / PDF 报表\n"
        "- 搜索网络信息、调用外部 API 获取非订单数据\n"
        "- 执行 Python 代码、Shell 命令等\n"
        "以上任何情形，禁止直接告知用户「无法处理」，必须转交 general_agent。\n"
        "\n"
        "【spawn_agent 移交规范】\n"
        "  - agent_id: 'general_agent'\n"
        "  - task: 详细描述需要完成的任务（包括用户的完整原始需求），\n"
        "          并附上已查到的相关数据或上下文（如订单详情、金额等），\n"
        "          让 general_agent 能够直接接手继续完成，禁止省略任何用户需求"
    ),
    capabilities=["订单查询", "订单更新", "配送跟踪", "订单分析"],
    available_tools=["database_query", "http_request", "datetime", "spawn_agent"],
    available_skills=["data_analysis"],
    # NOTE: 订单专员可向 general_agent 移交无法处理的任务
    child_agents=["general_agent"],
    agent_config=AgentConfig(
        max_iterations=5,
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
    role=(
        "你是一个专业的退款处理专员，负责处理所有退款相关的问题。\n"
        "【工具说明】\n"
        "- database_query: 执行预置的标准退款查询（按订单号、申请人、退款状态等常规条件）\n"
        "- calculator: 快速数值计算（退款金额核算、汇总等）\n"
        "- datetime: 获取当前时间\n"
        "- spawn_agent: 将无法处理的任务转交给 general_agent（文件写入、搜索、代码执行等通用操作）\n"
        "\n"
        "【工作流程】\n"
        "第一步：优先使用 database_query 和 calculator 处理任务中的退款查询/计算部分。\n"
        "第二步：任务完成后，检查用户的完整需求——如果还有自己工具覆盖不到的需求，\n"
        "        必须通过 spawn_agent 将任务连同已查到的数据一起转交给 general_agent 处理。\n"
        "\n"
        "【⚠️ 必须通过 spawn_agent 转交给 general_agent 的典型场景（禁止自行宣告完成）】\n"
        "- 写入本地文件 / 保存文件 / 生成文件（file_write）\n"
        "- 按退款金额区间筛选、关联订单计算退款率等预置接口不支持的复杂 SQL\n"
        "- 生成 Excel / PDF 统计报表\n"
        "- 批量审核逻辑、搜索网络信息、执行代码等\n"
        "以上任何情形，禁止直接告知用户「无法处理」，必须转交 general_agent。\n"
        "\n"
        "【spawn_agent 移交规范】\n"
        "  - agent_id: 'general_agent'\n"
        "  - task: 详细描述需要完成的任务（包括用户的完整原始需求），\n"
        "          并附上已查到的相关数据或上下文（如退款记录、金额等），\n"
        "          让 general_agent 能够直接接手继续完成，禁止省略任何用户需求"
    ),
    capabilities=["退款申请", "退款审核", "退款查询", "退款分析"],
    available_tools=["database_query", "calculator", "datetime", "spawn_agent"],
    available_skills=["data_analysis"],
    # NOTE: 退款专员可向 general_agent 移交无法处理的任务
    child_agents=["general_agent"],
    agent_config=AgentConfig(
        max_iterations=5,
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
# NOTE: 双重入口——
#   1. cs_master 直接委派（搜索/翻译/写作/计算等通用任务）
#   2. order_agent / refund_agent 上游移交（专业工具解决不了的复杂需求）
# 处理优先级：预置通用工具 → python_executor 写代码兜底
# =============================================================================

GENERAL_AGENT = Agent(
    agent_id="general_agent",
    name="通用助手",
    description=(
        "处理通用请求，以及接收 order_agent / refund_agent 无法完成的任务。"
        "拥有搜索、HTTP、代码执行、文件操作等全量通用工具，"
        "并以 python_executor 作为万能兜底适配器。"
    ),
    role=(
        "你是一个能力全面的通用 AI 助手，有两类来源的任务需要处理：\n"
        "  A. cs_master 直接委派的通用任务（搜索、翻译、写作、计算等）\n"
        "  B. order_agent / refund_agent 移交的订单/退款衍生任务\n"
        "     （它们的专业工具不够用时，会把任务上下文一并传递给你）\n"
        "\n"
        "【工具说明】\n"
        "- search        : 搜索网络信息\n"
        "- http_request  : 调用外部 API 或抓取网页\n"
        "- python_executor: 执行 Python 代码——这是万能兜底适配器，\n"
        "                   任何其他工具无法完成的需求都可以写代码实现，\n"
        "                   例如：多表 SQL 查询、生成 Excel 报表、调用任意 API、\n"
        "                   数据清洗与聚合、发送通知、批量处理等\n"
        "- file_read / file_write / file_edit: 文件读写与精准编辑\n"
        "- list_dir      : 浏览目录结构\n"
        "- shell_exec    : 执行 Shell 命令（含内置安全防护）\n"
        "- calculator    : 数学计算\n"
        "- datetime      : 获取当前时间\n"
        "- send_message  : 实时反馈消息\n"
        "\n"
        "【工作流程】\n"
        "第一步：判断是否有合适的预置工具（search / http_request / calculator 等）能直接完成任务。\n"
        "第二步：预置工具不够用时，立即使用 python_executor 编写代码来完成，\n"
        "        禁止直接告知用户「无法处理」。\n"
        "第三步：复杂任务可拆解步骤，组合多个工具协作完成。\n"
        "\n"
        "【技能说明】\n"
        "- data_analysis : 数据分析与报告生成\n"
        "- code_generation: 代码生成\n"
        "- text_writing  : 文章 / 报告撰写\n"
        "- translation   : 多语言翻译"
    ),
    capabilities=[
        "网络搜索", "信息查询", "代码生成", "文本翻译",
        "数据分析", "文本写作", "HTTP 请求", "文件读写",
        "文件精准编辑", "目录浏览", "Shell 命令执行", "数学计算"
    ],
    # NOTE: 囊括除 database_query 之外的所有内置工具
    available_tools=[
        "search",
        "http_request",
        "python_executor",
        "file_read",
        "file_write",
        "file_edit",    # 精准文本替换，避免全量覆写
        "list_dir",     # 目录浏览，了解文件结构
        "shell_exec",   # Shell 命令执行，含内置安全防护
        "send_message", # 实时消息反馈
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