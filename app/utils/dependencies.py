"""
API 依赖注入函数模块 (Dependency Injection Functions)
====================================================

本模块集中管理所有 API 端点的依赖注入函数。
采用懒加载单例模式，确保服务实例在整个应用生命周期内只初始化一次。

设计原则：
  1. 懒加载：首次调用时初始化，后续复用同一个实例
  2. 单例模式：全局共享同一个服务实例，避免重复创建
  3. 统一管理：所有 Depends 依赖注入函数集中在此，便于维护和调试

包含的依赖注入函数：
  1. get_automation_service()    - 自动化服务实例
  2. get_agent_registry()        - Agent 注册表实例
  3. get_agent_executor()        - Agent 执行器实例
  4. get_chat_service()          - 对话服务实例
  5. get_skill_manager()         - 技能管理器实例
  6. get_tool_hub()              - 工具中心实例
  7. get_workflow_engine()       - 工作流引擎实例
  8. get_workflows()             - 工作流字典实例

作者: AI Agent Team
创建时间: 2026-02-25
"""

from loguru import logger
from colorama import Fore, Style

# ============================================================================
# 全局服务实例变量（用于懒加载单例模式）
# ============================================================================

# 自动化服务相关
_automation_service = None

# Agent 相关
_agent_registry = None
_agent_executor = None
_child_agent_manager = None

# 对话服务相关
_chat_service = None

# 技能管理相关
_skill_manager = None

# 工具中心相关
_tool_hub = None

# 工作流相关
_workflow_engine = None
_workflows = {}


# ============================================================================
# 自动化服务依赖注入函数
# ============================================================================

def get_automation_service():
    """
    获取 AutomationService 实例（依赖注入）
    
    懒加载：首次调用时初始化，后续复用同一个实例。
    负责初始化 OpenAI Provider、Model Registry、Inference Engine、ToolHub 和 SkillManager。
    
    Returns:
        AutomationService: 自动化服务实例
    """
    global _automation_service
    if _automation_service is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 AutomationService...{Style.RESET_ALL}")

        from app.llm_hub.providers.openai import OpenAIProvider
        from app.llm_hub.registry import ModelRegistry
        from app.core.config import settings
        from app.llm_hub.inference import InferenceEngine
        from app.tools.hub import ToolHub
        from app.skills.manager import SkillManager
        from app.services.automation_service import AutomationService
        from app.tools.builtin import register_all_builtin_tools
        from app.skills.library import register_all_builtin_skills

        # 创建推理引擎（需要 provider 和 model_registry）
        provider = OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL
        )
        model_registry = ModelRegistry()
        inference_engine = InferenceEngine(
            provider=provider,
            model_registry=model_registry
        )

        # 初始化工具和技能管理器
        tool_hub = ToolHub()
        skill_manager = SkillManager()

        # 注册所有内置工具和技能
        register_all_builtin_tools(tool_hub)
        register_all_builtin_skills(skill_manager)

        # 创建自动化服务
        _automation_service = AutomationService(
            llm_hub=inference_engine,
            tool_hub=tool_hub,
            skill_manager=skill_manager
        )
        logger.info(f"{Fore.GREEN}【依赖注入】AutomationService 初始化完成{Style.RESET_ALL}")

    return _automation_service


# ============================================================================
# Agent 相关依赖注入函数
# ============================================================================

def get_agent_registry():
    """
    获取 AgentRegistry 实例（依赖注入）
    
    负责初始化 Agent 注册表，并注册所有内置 Agent。
    
    Returns:
        AgentRegistry: Agent 注册表实例
    """
    global _agent_registry
    if _agent_registry is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 AgentRegistry...{Style.RESET_ALL}")
        from app.agents.registry import AgentRegistry
        from app.agents.library.customer_service import register_customer_service_agents
        
        _agent_registry = AgentRegistry()
        
        # 注册所有内置 Agent
        register_customer_service_agents(_agent_registry)
        
        logger.info(f"{Fore.GREEN}【依赖注入】AgentRegistry 初始化完成{Style.RESET_ALL}")
    
    return _agent_registry


def get_agent_executor():
    """
    获取 LangGraphAgentExecutor 实例（依赖注入）
    
    同时初始化 ChildAgentManager，使父 Agent 能够将任务委派给子 Agent。
    负责初始化 OpenAI Provider、Model Registry、Inference Engine、ToolHub、SkillManager 等。
    
    Returns:
        LangGraphAgentExecutor: Agent 执行器实例
    """
    global _agent_executor, _child_agent_manager
    if _agent_executor is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 LangGraphAgentExecutor...{Style.RESET_ALL}")
        
        # 导入所需模块
        from app.llm_hub.providers.openai import OpenAIProvider
        from app.llm_hub.registry import ModelRegistry
        from app.core.config import settings
        from app.llm_hub.inference import InferenceEngine
        from app.tools.hub import ToolHub
        from app.skills.manager import SkillManager
        from app.agents.langgraph_executor import LangGraphAgentExecutor
        from app.agents.child_agent_manager import ChildAgentManager
        from app.tools.builtin import register_all_builtin_tools
        from app.skills.library import register_all_builtin_skills
        
        # 创建默认 LLM Provider（使用 OpenAI 兼容接口）
        provider = OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL
        )
        logger.debug(f"{Fore.CYAN}【依赖注入】已创建 OpenAIProvider（base_url={settings.OPENAI_BASE_URL}）{Style.RESET_ALL}")
        
        # 创建模型注册中心
        model_registry = ModelRegistry()
        logger.debug(f"{Fore.CYAN}【依赖注入】已创建 ModelRegistry{Style.RESET_ALL}")
        
        # 创建推理引擎（需要 provider 和 model_registry 两个必填参数）
        inference_engine = InferenceEngine(
            provider=provider,
            model_registry=model_registry
        )
        logger.debug(f"{Fore.CYAN}【依赖注入】已创建 InferenceEngine{Style.RESET_ALL}")
        
        tool_hub = ToolHub()
        skill_manager = SkillManager()
        
        # 注册所有内置工具和技能
        register_all_builtin_tools(tool_hub)
        register_all_builtin_skills(skill_manager)
        
        # 获取 Agent 注册表（确保已初始化）
        agent_registry = get_agent_registry()
        
        # 创建子 Agent 管理器，让父 Agent 能把任务委派给子 Agent
        _child_agent_manager = ChildAgentManager(
            agent_registry=agent_registry,
            llm_hub=inference_engine,
            tool_hub=tool_hub,
            skill_manager=skill_manager
        )
        logger.debug(f"{Fore.CYAN}【依赖注入】已创建 ChildAgentManager，支持多层 Agent 委派{Style.RESET_ALL}")
        
        # 创建执行器，传入子 Agent 管理器
        _agent_executor = LangGraphAgentExecutor(
            llm_hub=inference_engine,
            tool_hub=tool_hub,
            skill_manager=skill_manager,
            child_agent_manager=_child_agent_manager
        )
        
        logger.info(f"{Fore.GREEN}【依赖注入】LangGraphAgentExecutor 初始化完成（含 ChildAgentManager）{Style.RESET_ALL}")
    
    return _agent_executor


# ============================================================================
# 对话服务依赖注入函数
# ============================================================================

def get_chat_service():
    """
    获取 ChatService 实例（依赖注入）
    
    懒加载：首次调用时初始化，后续复用同一个实例。
    负责初始化 OpenAI Provider、Model Registry、Inference Engine 和 ShortTermMemory。
    
    Returns:
        ChatService: 对话服务实例
    """
    global _chat_service
    if _chat_service is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 ChatService...{Style.RESET_ALL}")

        from app.llm_hub.providers.openai import OpenAIProvider
        from app.llm_hub.registry import ModelRegistry
        from app.core.config import settings
        from app.llm_hub.inference import InferenceEngine
        from app.services.chat_service import ChatService
        from app.memory.short_term import ShortTermMemory

        # 创建 LLM Provider（使用 OpenAI 兼容接口）
        provider = OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL
        )
        logger.debug(
            f"{Fore.CYAN}【依赖注入】已创建 OpenAIProvider "
            f"(base_url={settings.OPENAI_BASE_URL}){Style.RESET_ALL}"
        )

        # 创建推理引擎
        model_registry = ModelRegistry()
        inference_engine = InferenceEngine(
            provider=provider,
            model_registry=model_registry
        )

        # 创建短期记忆（最多保留 10 条历史消息）
        memory = ShortTermMemory(max_messages=10)

        # 创建对话服务
        _chat_service = ChatService(llm_hub=inference_engine, memory=memory)
        logger.info(f"{Fore.GREEN}【依赖注入】ChatService 初始化完成{Style.RESET_ALL}")

    return _chat_service


# ============================================================================
# 技能管理依赖注入函数
# ============================================================================

def get_skill_manager():
    """
    获取 SkillManager 实例（依赖注入）
    
    负责初始化技能管理器，并注册所有内置技能。
    
    Returns:
        SkillManager: 技能管理器实例
    """
    global _skill_manager
    if _skill_manager is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 SkillManager...{Style.RESET_ALL}")
        from app.skills.manager import SkillManager
        from app.skills.library import register_all_builtin_skills
        
        _skill_manager = SkillManager()
        
        # 注册所有内置技能
        register_all_builtin_skills(_skill_manager)
        
        logger.info(f"{Fore.GREEN}【依赖注入】SkillManager 初始化完成{Style.RESET_ALL}")
    
    return _skill_manager


# ============================================================================
# 工具中心依赖注入函数
# ============================================================================

def get_tool_hub():
    """
    获取 ToolHub 实例（依赖注入）
    
    负责初始化工具中心，并注册所有内置工具。
    
    Returns:
        ToolHub: 工具中心实例
    """
    global _tool_hub
    if _tool_hub is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 ToolHub...{Style.RESET_ALL}")
        from app.tools.hub import ToolHub
        from app.tools.builtin import register_all_builtin_tools
        
        _tool_hub = ToolHub()
        
        # 注册所有内置工具
        register_all_builtin_tools(_tool_hub)
        
        logger.info(f"{Fore.GREEN}【依赖注入】ToolHub 初始化完成{Style.RESET_ALL}")
    
    return _tool_hub


# ============================================================================
# 工作流相关依赖注入函数
# ============================================================================

def get_workflow_engine():
    """
    获取 WorkflowEngine 实例（依赖注入）
    
    负责初始化工作流引擎。
    
    Returns:
        WorkflowEngine: 工作流引擎实例
    """
    global _workflow_engine
    if _workflow_engine is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 WorkflowEngine...{Style.RESET_ALL}")
        from app.workflows.engine import WorkflowEngine
        
        _workflow_engine = WorkflowEngine()
        logger.info(f"{Fore.GREEN}【依赖注入】WorkflowEngine 初始化完成{Style.RESET_ALL}")
    
    return _workflow_engine


def get_workflows():
    """
    获取所有工作流（依赖注入）
    
    负责加载所有内置工作流定义。
    
    Returns:
        Dict[str, Workflow]: 工作流字典
    """
    global _workflows
    if not _workflows:
        logger.info(f"{Fore.BLUE}【依赖注入】加载工作流定义...{Style.RESET_ALL}")
        
        # 注册所有内置工作流
        from app.workflows.templates.intent_routing import INTENT_ROUTING_WORKFLOW
        _workflows[INTENT_ROUTING_WORKFLOW.workflow_id] = INTENT_ROUTING_WORKFLOW
        
        logger.info(f"{Fore.GREEN}【依赖注入】工作流定义加载完成，共 {len(_workflows)} 个{Style.RESET_ALL}")
    
    return _workflows
