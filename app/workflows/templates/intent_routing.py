"""
意图路由工作流模板

本模块定义了意图路由工作流，用于根据用户意图自动路由到相应的技能。

工作流结构:
1. classify_intent: 使用LLM分类用户意图
2. route_decision: 根据意图条件路由到对应技能
3. 技能节点: data_skill, code_skill, translate_skill, chat_skill

支持的意图类型:
- data_analysis: 数据分析相关请求
- code_generation: 代码生成相关请求
- translation: 翻译相关请求
- general_chat: 一般对话请求
"""

from loguru import logger
from colorama import Fore, Style
from app.core.config import get_default_model
from app.workflows.nodes import Workflow, WorkflowNode, NodeType

# 意图路由工作流定义
INTENT_ROUTING_WORKFLOW = Workflow(
    workflow_id="intent_routing",
    name="意图路由工作流",
    description="根据用户意图自动路由到相应的AI技能进行处理",
    nodes=[
        # 节点1: 意图分类（LLM调用）
        WorkflowNode(
            node_id="classify_intent",
            node_type=NodeType.LLM_CALL,
            config={
                "prompt": """请分析用户的意图，并将其分类为以下类型之一:

1. data_analysis - 数据分析：用户需要分析数据、提取洞察、统计分析
2. code_generation - 代码生成：用户需要生成代码、编写程序、解决编程问题
3. translation - 翻译：用户需要翻译文本、多语言转换
4. general_chat - 一般对话：其他类型的对话和文本写作需求

请只返回分类结果，格式为: data_analysis 或 code_generation 或 translation 或 general_chat
""",
                "model": get_default_model("openai"),
                "temperature": 0.1  # 低温度确保分类稳定性
            },
            inputs=[],
            outputs=["route_decision"]
        ),
        
        # 节点2: 路由决策（条件分支）
        WorkflowNode(
            node_id="route_decision",
            node_type=NodeType.CONDITION,
            config={
                "conditions": {
                    "data_analysis": "data_skill",
                    "code_generation": "code_skill",
                    "translation": "translate_skill",
                    "general_chat": "chat_skill"
                }
            },
            inputs=["classify_intent"],
            outputs=["data_skill", "code_skill", "translate_skill", "chat_skill"]
        ),
        
        # 节点3: 数据分析技能
        WorkflowNode(
            node_id="data_skill",
            node_type=NodeType.SKILL_CALL,
            config={
                "skill_id": "data_analysis"
            },
            inputs=["route_decision"],
            outputs=[]
        ),
        
        # 节点4: 代码生成技能
        WorkflowNode(
            node_id="code_skill",
            node_type=NodeType.SKILL_CALL,
            config={
                "skill_id": "code_generation"
            },
            inputs=["route_decision"],
            outputs=[]
        ),
        
        # 节点5: 翻译技能
        WorkflowNode(
            node_id="translate_skill",
            node_type=NodeType.SKILL_CALL,
            config={
                "skill_id": "translation"
            },
            inputs=["route_decision"],
            outputs=[]
        ),
        
        # 节点6: 对话技能（使用文本写作技能）
        WorkflowNode(
            node_id="chat_skill",
            node_type=NodeType.SKILL_CALL,
            config={
                "skill_id": "text_writing"
            },
            inputs=["route_decision"],
            outputs=[]
        )
    ],
    edges=[
        # 从意图分类到路由决策
        ["classify_intent", "route_decision"],
        # 从路由决策到各个技能（条件边）
        ["route_decision", "data_skill"],
        ["route_decision", "code_skill"],
        ["route_decision", "translate_skill"],
        ["route_decision", "chat_skill"]
    ],
    entry_node="classify_intent",
    exit_nodes=["data_skill", "code_skill", "translate_skill", "chat_skill"]
)

logger.info(f"{Fore.GREEN}[意图路由工作流] INTENT_ROUTING_WORKFLOW 已定义{Style.RESET_ALL}")
logger.debug(f"{Fore.CYAN}[意图路由工作流] 节点数量: {len(INTENT_ROUTING_WORKFLOW.nodes)}, 边数量: {len(INTENT_ROUTING_WORKFLOW.edges)}{Style.RESET_ALL}")
