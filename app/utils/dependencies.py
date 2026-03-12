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
  7. get_tool_calling_gateway()  - 工具调用网关实例（NEW）
  8. get_workflow_engine()       - 工作流引擎实例
  9. get_workflows()             - 工作流字典实例

工具调用网关集成说明：
  ToolCallingGateway 是 LLM Hub 的核心组件，负责处理 LLM 的原生工具调用请求。
  当 LLM 返回 finish_reason=tool_calls 时，推理引擎会通过网关执行工具，
  将工具结果追加到对话历史，再次调用 LLM，形成"原生工具调用循环"。
  
  网关与 ToolHub 的区别：
  - ToolHub: 管理工具注册和查找，由 ExecutionEngine 在"规划执行"模式下直接调用
  - ToolCallingGateway: 专为 LLM 原生工具调用设计，处理 OpenAI/Anthropic 格式的 tool_calls 响应
  
  两种工具调用模式：
  1. 规划执行模式（Planning → Execution）：LLM 生成文本计划 → ExecutionEngine 执行 → 使用 ToolHub
  2. 原生工具调用模式（Native Tool Calling）：LLM 直接返回 tool_calls → Gateway 执行 → 结果追加对话

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

# 工具调用网关相关（NEW：核心新增组件）
# 负责处理 LLM 的原生工具调用响应，与 InferenceEngine 协同工作
_tool_calling_gateway = None

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
    负责初始化 OpenAI Provider、Model Registry、Inference Engine（含 ToolCallingGateway）、
    ToolHub 和 SkillManager。
    
    工具调用网关集成：
    AutomationService 的 InferenceEngine 集成了 ToolCallingGateway，
    这意味着当 AutomationService 调用 LLM 时，如果请求中包含工具定义（config.tools 非空），
    且 LLM 返回 finish_reason=tool_calls，InferenceEngine 会自动通过网关执行工具，
    实现真正的 LLM 原生工具调用能力。
    
    Returns:
        AutomationService: 自动化服务实例
    """
    global _automation_service
    if _automation_service is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 AutomationService（含工具调用网关）...{Style.RESET_ALL}")

        from app.llm_hub.providers.openai import OpenAIProvider
        from app.llm_hub.registry import ModelRegistry
        from app.core.config import settings
        from app.llm_hub.inference import InferenceEngine
        from app.tools.hub import ToolHub
        from app.skills.manager import SkillManager
        from app.services.automation_service import AutomationService
        from app.tools.builtin import register_all_builtin_tools
        from app.skills.library import register_all_builtin_skills

        # 创建 LLM 供应商（使用 OpenAI 兼容接口）
        provider = OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL
        )
        logger.debug(f"{Fore.CYAN}【依赖注入】已创建 OpenAIProvider{Style.RESET_ALL}")
        
        model_registry = ModelRegistry()
        logger.debug(f"{Fore.CYAN}【依赖注入】已创建 ModelRegistry{Style.RESET_ALL}")
        
        # 初始化工具和技能管理器（先创建，以便同步工具到网关）
        tool_hub = ToolHub()
        skill_manager = SkillManager()

        # 注册所有内置工具和技能
        register_all_builtin_tools(tool_hub)
        register_all_builtin_skills(skill_manager)
        logger.debug(
            f"{Fore.CYAN}【依赖注入】已注册 {len(tool_hub.list_tools())} 个内置工具，"
            f"{len(skill_manager.list_skills())} 个内置技能{Style.RESET_ALL}"
        )
        
        # ── 获取工具调用网关 ──────────────────────────────────────────────
        # 注意：get_tool_calling_gateway() 内部会调用 get_tool_hub()，
        # 而 get_tool_hub() 是全局 ToolHub 单例（已注册所有内置工具）。
        # AutomationService 这里使用的是独立的 tool_hub 实例（非单例），
        # 所以需要将其工具也同步到网关（或者也使用全局单例 tool_hub）。
        # 
        # 当前策略：AutomationService 使用全局 ToolCallingGateway（已同步全局 ToolHub 的工具），
        # 而 AutomationService 的 tool_hub 也包含相同的工具。两者工具集一致。
        tool_calling_gateway = get_tool_calling_gateway()
        logger.debug(
            f"{Fore.CYAN}【依赖注入】已获取 ToolCallingGateway，"
            f"可用工具: {list(tool_calling_gateway._tools.keys())}{Style.RESET_ALL}"
        )
        
        # 创建推理引擎（集成工具调用网关）
        # 当 AutomationService 在 LLM 调用中传入 config.tools 时，
        # InferenceEngine 会自动处理 LLM 的工具调用响应，形成工具调用循环
        inference_engine = InferenceEngine(
            provider=provider,
            model_registry=model_registry,
            tool_gateway=tool_calling_gateway,  # 集成工具调用网关（核心新增）
            max_tool_iterations=20  # 最大工具调用循环次数，防止无限循环
        )
        logger.debug(
            f"{Fore.CYAN}【依赖注入】已创建集成 ToolCallingGateway 的 InferenceEngine{Style.RESET_ALL}"
        )

        # 创建自动化服务
        _automation_service = AutomationService(
            llm_hub=inference_engine,
            tool_hub=tool_hub,
            skill_manager=skill_manager
        )
        logger.info(
            f"{Fore.GREEN}【依赖注入】AutomationService 初始化完成（含 ToolCallingGateway 支持）{Style.RESET_ALL}"
        )

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
    负责初始化 OpenAI Provider、Model Registry、Inference Engine（含 ToolCallingGateway）、
    ToolHub、SkillManager 等。
    
    工具调用网关集成说明（已升级）：
    ToolCallingGateway 现在真正介入主流程，完整调用链路如下：
    
    Planning Engine（LLM 生成 JSON 计划）
        ↓
    Execution Engine._execute_tool()
        ↓ 优先调用
    ToolCallingGateway.execute_direct_tool_call()  ← 工具调用统一入口
        ├── 参数 JSON Schema 校验
        ├── 超时控制
        ├── 执行统计（call_count / success_rate / avg_time）
        └── 统一错误处理
        ↓
    tool.execute(params)（最终执行工具）
    
    当网关执行异常时，ExecutionEngine 会自动降级为直接调用 ToolHub，保证流程不中断。
    
    Returns:
        LangGraphAgentExecutor: Agent 执行器实例
    """
    global _agent_executor, _child_agent_manager
    if _agent_executor is None:
        logger.info(
            f"{Fore.BLUE}【依赖注入】初始化 LangGraphAgentExecutor（含 ToolCallingGateway）...{Style.RESET_ALL}"
        )
        
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
        
        # 初始化工具和技能管理器（先创建，让工具注册完成后再同步到网关）
        tool_hub = ToolHub()
        skill_manager = SkillManager()
        
        # 注册所有内置工具和技能
        register_all_builtin_tools(tool_hub)
        register_all_builtin_skills(skill_manager)
        logger.debug(
            f"{Fore.CYAN}【依赖注入】已注册 {len(tool_hub.list_tools())} 个内置工具，"
            f"{len(skill_manager.list_skills())} 个内置技能{Style.RESET_ALL}"
        )
        
        # ── 获取工具调用网关 ──────────────────────────────────────────────
        # 注意：Agent 执行器的主要工具调用方式是通过 ExecutionEngine 直接调用 ToolHub，
        # 这是"规划执行"模式，不需要 ToolCallingGateway。
        # ToolCallingGateway 在这里是为了支持未来的"原生工具调用"扩展，
        # 以及当 Planning/Execution 流程中某些场景需要 LLM 直接调用工具时使用。
        tool_calling_gateway = get_tool_calling_gateway()
        logger.debug(
            f"{Fore.CYAN}【依赖注入】已获取 ToolCallingGateway（Agent Executor 备用）{Style.RESET_ALL}"
        )
        
        # 创建推理引擎（集成工具调用网关）
        # 说明：当前 Agent 系统主要使用"规划执行"模式，Planning Engine 调用 LLM 生成文本计划，
        # Execution Engine 直接执行。这些 LLM 调用不传 config.tools，所以不会触发网关。
        # 网关在 InferenceEngine 中是"按需激活"的（仅当 config.tools 非空时才生效）。
        inference_engine = InferenceEngine(
            provider=provider,
            model_registry=model_registry,
            tool_gateway=tool_calling_gateway,  # 集成工具调用网关（备用，不影响主流程）
            max_tool_iterations=20
        )
        logger.debug(
            f"{Fore.CYAN}【依赖注入】已创建集成 ToolCallingGateway 的 InferenceEngine{Style.RESET_ALL}"
        )
        
        # 获取 Agent 注册表（确保已初始化）
        agent_registry = get_agent_registry()
        
        # 创建子 Agent 管理器，让父 Agent 能把任务委派给子 Agent
        # 同时传入 tool_calling_gateway，确保子 Agent 的工具调用也走统一网关路径
        _child_agent_manager = ChildAgentManager(
            agent_registry=agent_registry,
            llm_hub=inference_engine,
            tool_hub=tool_hub,
            skill_manager=skill_manager,
            tool_gateway=tool_calling_gateway  # 【关键】注入网关到 ChildAgentManager
        )
        logger.debug(
            f"{Fore.CYAN}【依赖注入】已创建 ChildAgentManager（含 ToolCallingGateway），"
            f"支持多层 Agent 委派{Style.RESET_ALL}"
        )

        # ── 注册 SpawnAgentTool 到 ToolHub 和 Gateway ───────────────────────────
        # NOTE: SpawnAgentTool 必须在 _child_agent_manager 创建后才能注册，
        #       因为它需要注入 ChildAgentManager 实例（运行时依赖）。
        # 注册后，cs_master 等主 Agent 可以在执行计划步骤中调用 spawn_agent 工具
        # 将子任务委派给 order_agent / refund_agent / general_agent 等子 Agent。
        # SpawnAgentTool 的 stream_callback / pending_confirmations 在每次
        # execute_with_callback 调用时通过 update_context() 动态更新。
        from app.tools.builtin.spawn import SpawnAgentTool
        spawn_tool = SpawnAgentTool(
            child_agent_manager=_child_agent_manager,
            parent_agent_id=None,       # 父 Agent ID 在执行时动态设置
            stream_callback=None,       # 流式回调在执行时动态更新
            pending_confirmations=None  # 确认字典在执行时动态更新
        )
        tool_hub.register_tool(spawn_tool)
        tool_calling_gateway.register_tool(
            name=spawn_tool.name,
            tool_instance=spawn_tool,
            schema=spawn_tool.schema.parameters
        )
        logger.info(
            f"{Fore.GREEN}【依赖注入】SpawnAgentTool 已注册到 ToolHub 和 Gateway "
            f"| tool_name={spawn_tool.name}{Style.RESET_ALL}"
        )

        # ── 注册 MessageAgentTool 到 ToolHub 和 Gateway ─────────────────────────
        # NOTE: 允许 Agent 在执行过程中通过工具调用主动向用户发送实时进度消息。
        #       它的 stream_callback 同样在 execute_with_callback 时动态更新。
        from app.tools.builtin.message import MessageAgentTool
        message_tool = MessageAgentTool(stream_callback=None)
        tool_hub.register_tool(message_tool)
        tool_calling_gateway.register_tool(
            name=message_tool.name,
            tool_instance=message_tool,
            schema=message_tool.schema.parameters
        )
        logger.info(
            f"{Fore.GREEN}【依赖注入】MessageAgentTool 已注册到 ToolHub 和 Gateway "
            f"| tool_name={message_tool.name}{Style.RESET_ALL}"
        )

        # 创建执行器，传入子 Agent 管理器 和 工具网关
        # 【关键修改】：tool_gateway 注入给 LangGraphAgentExecutor，
        # 它会进一步传给 ExecutionEngine，使 _execute_tool() 优先走网关路径，
        # 真正让 ToolCallingGateway 介入每一次工具执行
        _agent_executor = LangGraphAgentExecutor(
            llm_hub=inference_engine,
            tool_hub=tool_hub,
            skill_manager=skill_manager,
            child_agent_manager=_child_agent_manager,
            tool_gateway=tool_calling_gateway  # 【关键】注入网关到执行引擎
        )
        
        logger.info(
            f"{Fore.GREEN}【依赖注入】LangGraphAgentExecutor 初始化完成"
            f"（含 ChildAgentManager + ToolCallingGateway，工具调用路径：ExecutionEngine → Gateway → Tool）{Style.RESET_ALL}"
        )
    
    return _agent_executor


# ============================================================================
# 对话服务依赖注入函数
# ============================================================================

def get_chat_service():
    """
    获取 ChatService 实例（依赖注入）
    
    懒加载：首次调用时初始化，后续复用同一个实例。
    负责初始化 OpenAI Provider、Model Registry、Inference Engine（含 ToolCallingGateway）
    和 ShortTermMemory。
    
    工具调用网关集成说明：
    ChatService 的 InferenceEngine 集成了 ToolCallingGateway，
    当对话请求中包含工具定义（config.tools 非空）时，
    LLM 可以通过 tool_calls 请求调用工具，网关会自动处理工具执行和对话循环。
    当前 ChatService 的普通对话（不传 tools）不受影响，网关按需激活。
    
    Returns:
        ChatService: 对话服务实例
    """
    global _chat_service
    if _chat_service is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 ChatService（含 ToolCallingGateway）...{Style.RESET_ALL}")

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

        # 创建模型注册中心
        model_registry = ModelRegistry()
        logger.debug(f"{Fore.CYAN}【依赖注入】已创建 ModelRegistry{Style.RESET_ALL}")
        
        # ── 获取工具调用网关 ──────────────────────────────────────────────
        # ChatService 的 InferenceEngine 配备网关后，
        # 支持在对话时动态传入工具定义（config.tools），让 LLM 自主决定是否调用工具。
        # 当前基本的文本对话（不传 tools）不会触发工具调用循环，兼容现有行为。
        tool_calling_gateway = get_tool_calling_gateway()
        logger.debug(
            f"{Fore.CYAN}【依赖注入】已获取 ToolCallingGateway（ChatService 工具调用支持）{Style.RESET_ALL}"
        )
        
        # 创建推理引擎（集成工具调用网关）
        inference_engine = InferenceEngine(
            provider=provider,
            model_registry=model_registry,
            tool_gateway=tool_calling_gateway,  # 集成工具调用网关（核心新增）
            max_tool_iterations=20
        )
        logger.debug(
            f"{Fore.CYAN}【依赖注入】已创建集成 ToolCallingGateway 的 InferenceEngine{Style.RESET_ALL}"
        )

        # 创建短期记忆（最多保留 10 条历史消息）
        memory = ShortTermMemory(max_messages=10)

        # 创建对话服务
        _chat_service = ChatService(llm_hub=inference_engine, memory=memory)
        logger.info(
            f"{Fore.GREEN}【依赖注入】ChatService 初始化完成（含 ToolCallingGateway 支持）{Style.RESET_ALL}"
        )

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
# 工具调用网关依赖注入函数（新增核心组件）
# ============================================================================

def _sync_tools_to_gateway(tool_hub, gateway) -> int:
    """
    将 ToolHub 中的所有工具同步注册到 ToolCallingGateway
    
    这是 ToolHub 和 ToolCallingGateway 之间的桥接函数。
    ToolHub 是工具的注册中心（存储工具实例），
    ToolCallingGateway 是工具执行引擎（处理 LLM 的 tool_calls 响应）。
    两者需要保持工具注册的同步，才能在 LLM 原生工具调用时找到并执行正确的工具。
    
    Schema 格式说明：
    - ToolSchema.parameters 是 JSON Schema 格式的参数定义，例如：
        {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    - ToolCallingGateway.register_tool() 接收的 schema 参数就是这个 parameters 字典
    
    Args:
        tool_hub: ToolHub 实例（工具来源）
        gateway: ToolCallingGateway 实例（工具目标注册位置）
        
    Returns:
        int: 成功同步的工具数量
    """
    tools = tool_hub.list_tools()
    synced_count = 0
    
    logger.info(
        f"{Fore.BLUE}【工具同步】开始将 ToolHub 中的工具同步到 ToolCallingGateway，"
        f"共 {len(tools)} 个工具{Style.RESET_ALL}"
    )
    
    for tool in tools:
        try:
            # 获取工具的参数 Schema（JSON Schema 格式）
            # tool.schema 是 ToolSchema 对象，.parameters 是具体的参数定义
            tool_schema = tool.schema
            parameters_schema = tool_schema.parameters
            
            # 向网关注册工具
            # 注意：这里使用 parameters 作为 schema，而不是完整的 ToolSchema，
            # 因为 ToolCallingGateway 的参数验证逻辑期望的是 JSON Schema 参数格式
            gateway.register_tool(
                name=tool.name,
                tool_instance=tool,
                schema=parameters_schema
            )
            
            synced_count += 1
            logger.debug(
                f"{Fore.CYAN}【工具同步】已同步工具: {tool.name}{Style.RESET_ALL}"
            )
            
        except Exception as e:
            logger.warning(
                f"{Fore.YELLOW}【工具同步】同步工具 '{tool.name}' 时发生异常: {e}，跳过该工具{Style.RESET_ALL}"
            )
    
    logger.info(
        f"{Fore.GREEN}【工具同步】工具同步完成，成功同步 {synced_count}/{len(tools)} 个工具{Style.RESET_ALL}"
    )
    
    return synced_count


def get_tool_calling_gateway():
    """
    获取 ToolCallingGateway 实例（依赖注入）
    
    懒加载：首次调用时初始化，后续复用同一个实例。
    
    功能说明：
    ToolCallingGateway 是处理 LLM 原生工具调用的核心组件。
    当 LLM 返回 finish_reason=tool_calls 时（即 LLM 决定调用工具），
    InferenceEngine 会通过此网关：
      1. 解析 LLM 响应中的 tool_calls 列表（支持 OpenAI/Anthropic 格式）
      2. 查找对应的工具实例
      3. 验证并执行工具参数
      4. 返回格式化的工具结果（role=tool 格式，供下次 LLM 调用使用）
    
    网关初始化后会自动从 ToolHub 同步所有已注册工具，
    确保 LLM 请求的任何工具都能被正确找到和执行。
    
    Returns:
        ToolCallingGateway: 工具调用网关实例
    """
    global _tool_calling_gateway
    if _tool_calling_gateway is None:
        logger.info(f"{Fore.BLUE}【依赖注入】初始化 ToolCallingGateway...{Style.RESET_ALL}")
        
        from app.llm_hub.tool_gateway import ToolCallingGateway
        
        # 创建工具调用网关实例
        _tool_calling_gateway = ToolCallingGateway()
        logger.debug(f"{Fore.CYAN}【依赖注入】ToolCallingGateway 实例已创建{Style.RESET_ALL}")
        
        # 从 ToolHub 同步所有工具到网关
        # 这确保了 LLM 请求的任何工具都能在网关中找到并执行
        tool_hub = get_tool_hub()
        synced_count = _sync_tools_to_gateway(tool_hub, _tool_calling_gateway)
        
        # 获取网关当前可用工具列表，用于日志验证
        available_tools = list(_tool_calling_gateway._tools.keys())
        
        logger.info(
            f"{Fore.GREEN}【依赖注入】ToolCallingGateway 初始化完成，"
            f"已同步 {synced_count} 个工具: {available_tools}{Style.RESET_ALL}"
        )
    
    return _tool_calling_gateway


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
