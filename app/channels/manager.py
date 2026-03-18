"""
Channel Manager (渠道管理器)
================================

本模块负责渠道的注册、消息标准化和向应用层的分发。

数据流向：
  外部请求 → ChannelAdapter.receive_message() → ChannelMessage（标准格式）
           → _dispatch_to_application()        → ChatService / AutomationService / AgentExecutor
           → ChannelAdapter.send_message()     → 格式化响应

支持的 service_type（在消息 metadata 中指定）：
  - "chat"       : 对话服务（ChatService）
  - "agent"      : Agent 执行器（LangGraphAgentExecutor）
  - "automation" : 自动化服务（AutomationService）

作者: AI Agent Team
创建时间: 2026-02-15
"""

from typing import Dict, Any, Optional
from loguru import logger
from colorama import Fore, Style
from app.core.config import get_default_model
from app.channels.base import ChannelAdapter, ChannelMessage


class ChannelManager:
    """
    渠道管理器

    负责渠道的注册、消息路由和分发。
    通过注入服务依赖，将标准化消息分发到对应的应用层服务。
    """

    def __init__(self):
        # 注册的渠道适配器字典 {channel_id: adapter}
        self._adapters: Dict[str, ChannelAdapter] = {}

        # NOTE: 应用层服务依赖，通过 set_services() 注入，避免循环导入
        # 这三个服务在 main.py 启动阶段完成注入
        self._chat_service = None           # ChatService 实例
        self._agent_executor = None         # LangGraphAgentExecutor 实例
        self._automation_service = None     # AutomationService 实例

        logger.info(f"{Fore.BLUE}【渠道管理器】ChannelManager 初始化完成{Style.RESET_ALL}")

    def set_services(
        self,
        chat_service=None,
        agent_executor=None,
        automation_service=None
    ):
        """
        注入应用层服务依赖

        在 main.py lifespan 阶段调用，将三个核心服务绑定到 ChannelManager，
        使其能在 _dispatch_to_application 中将消息路由到正确的服务。

        Args:
            chat_service: ChatService 实例（处理对话请求）
            agent_executor: LangGraphAgentExecutor 实例（执行 Agent 任务）
            automation_service: AutomationService 实例（处理自动化任务）
        """
        self._chat_service = chat_service
        self._agent_executor = agent_executor
        self._automation_service = automation_service

        registered = []
        if chat_service:
            registered.append("ChatService")
        if agent_executor:
            registered.append("LangGraphAgentExecutor")
        if automation_service:
            registered.append("AutomationService")

        logger.info(
            f"{Fore.GREEN}【渠道管理器】已注入服务依赖: "
            f"{', '.join(registered) if registered else '（无）'}{Style.RESET_ALL}"
        )

    def register_channel(self, channel_id: str, adapter: ChannelAdapter):
        """
        注册渠道适配器

        Args:
            channel_id: 渠道唯一 ID，如 "rest_api"、"web_chat"、"wx_public"
            adapter: 对应的渠道适配器实例
        """
        self._adapters[channel_id] = adapter
        logger.info(
            f"{Fore.GREEN}【渠道管理器】已注册渠道: "
            f"{Fore.CYAN}{channel_id}{Style.RESET_ALL}"
        )

    def get_adapter(self, channel_id: str) -> Optional[ChannelAdapter]:
        """
        获取渠道适配器

        Args:
            channel_id: 渠道 ID

        Returns:
            ChannelAdapter 或 None
        """
        return self._adapters.get(channel_id)

    def list_channels(self) -> list:
        """
        列出所有已注册的渠道 ID

        Returns:
            渠道 ID 列表
        """
        return list(self._adapters.keys())

    async def route_message(self, channel_id: str, raw_message: Any) -> Any:
        """
        消息路由入口方法

        完整流程：
        1. 从注册的适配器中找到对应渠道
        2. 调用 adapter.receive_message() 将原始消息标准化为 ChannelMessage
        3. 调用 _dispatch_to_application() 将标准化消息分发到应用层服务
        4. 返回服务处理结果

        Args:
            channel_id: 来源渠道 ID（必须已注册）
            raw_message: 渠道原始消息数据

        Returns:
            应用层服务的处理结果（dict），失败时包含 "error" 字段

        Raises:
            ValueError: 当 channel_id 未注册时
        """
        logger.info(
            f"{Fore.BLUE}【渠道管理器】接收到消息 — 渠道: "
            f"{Fore.CYAN}{channel_id}{Style.RESET_ALL}"
        )

        # 步骤 1：查找渠道适配器
        adapter = self.get_adapter(channel_id)
        if not adapter:
            logger.error(
                f"{Fore.RED}【渠道管理器】渠道不存在: {channel_id}{Style.RESET_ALL}"
            )
            raise ValueError(f"渠道未注册: {channel_id}")

        # 步骤 2：消息标准化（渠道特定格式 → ChannelMessage 通用格式）
        try:
            message = await adapter.receive_message(raw_message)
            logger.info(
                f"{Fore.GREEN}【渠道管理器】消息标准化成功 — "
                f"消息ID: {message.message_id}, 用户: {message.sender_id}{Style.RESET_ALL}"
            )
        except Exception as e:
            logger.error(
                f"{Fore.RED}【渠道管理器】消息标准化失败 (渠道={channel_id}): {e}{Style.RESET_ALL}"
            )
            raise

        # 步骤 3：分发到应用层服务
        result = await self._dispatch_to_application(message)

        logger.info(
            f"{Fore.GREEN}【渠道管理器】消息处理完成 — "
            f"消息ID: {message.message_id}{Style.RESET_ALL}"
        )
        return result

    async def _dispatch_to_application(self, message: ChannelMessage) -> Dict[str, Any]:
        """
        将标准化消息分发到对应的应用层服务

        根据消息 metadata 中的 service_type 字段决定路由目标：
          - "chat"       → ChatService.chat()
          - "agent"      → LangGraphAgentExecutor.execute()
          - "automation" → AutomationService 的对应方法

        如果 service_type 未指定，默认路由到 ChatService（对话服务）。

        Args:
            message: 已标准化的 ChannelMessage 对象

        Returns:
            Dict[str, Any]: 应用层服务的处理结果
        """
        # 从消息元数据中读取目标服务类型，默认为 "chat"
        service_type = message.metadata.get("service_type", "chat")

        logger.info(
            f"{Fore.BLUE}【渠道管理器】分发消息到应用层 — "
            f"service_type={service_type}, "
            f"消息内容: {message.content[:50]}...{Style.RESET_ALL}"
        )

        # ── 对话服务 ─────────────────────────────────────────────
        if service_type == "chat":
            return await self._dispatch_to_chat(message)

        # ── Agent 执行器 ──────────────────────────────────────────
        elif service_type == "agent":
            return await self._dispatch_to_agent(message)

        # ── 自动化服务 ────────────────────────────────────────────
        elif service_type == "automation":
            return await self._dispatch_to_automation(message)

        # ── 未知类型 ──────────────────────────────────────────────
        else:
            logger.warning(
                f"{Fore.YELLOW}【渠道管理器】未知的 service_type: {service_type}，"
                f"降级为 chat 服务{Style.RESET_ALL}"
            )
            return await self._dispatch_to_chat(message)

    async def _dispatch_to_chat(self, message: ChannelMessage) -> Dict[str, Any]:
        """
        分发到对话服务 (ChatService)

        从 metadata 中提取对话相关参数，调用 ChatService.chat() 处理。

        Args:
            message: 标准化消息

        Returns:
            ChatService.chat() 的返回结果
        """
        logger.info(
            f"{Fore.CYAN}【渠道管理器→对话服务】处理对话请求, "
            f"sender={message.sender_id}{Style.RESET_ALL}"
        )

        if not self._chat_service:
            logger.error(f"{Fore.RED}【渠道管理器】ChatService 未注入！{Style.RESET_ALL}")
            return {"success": False, "error": "ChatService 未初始化，请检查服务启动配置"}

        # 从 metadata 中提取可选参数
        conversation_id = message.metadata.get("conversation_id", message.sender_id)
        system_prompt = message.metadata.get("system_prompt")
        model = message.metadata.get("model") or get_default_model("openai")
        temperature = message.metadata.get("temperature", 0.7)
        max_tokens = message.metadata.get("max_tokens", 2048)

        logger.debug(
            f"{Fore.CYAN}【渠道管理器→对话服务】参数: "
            f"conversation_id={conversation_id}, model={model}{Style.RESET_ALL}"
        )

        result = await self._chat_service.chat(
            conversation_id=conversation_id,
            message=message.content,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens
        )

        logger.info(
            f"{Fore.GREEN}【渠道管理器→对话服务】对话处理成功{Style.RESET_ALL}"
        )
        return result

    async def _dispatch_to_agent(self, message: ChannelMessage) -> Dict[str, Any]:
        """
        分发到 Agent 执行器 (LangGraphAgentExecutor)

        从 metadata 中读取 agent_id 和 conversation_history，
        查询 AgentRegistry 获取对应 Agent 并执行。

        Args:
            message: 标准化消息（content 即任务描述）

        Returns:
            LangGraphAgentExecutor.execute() 的返回结果
        """
        logger.info(
            f"{Fore.CYAN}【渠道管理器→Agent执行器】处理 Agent 请求, "
            f"sender={message.sender_id}{Style.RESET_ALL}"
        )

        if not self._agent_executor:
            logger.error(f"{Fore.RED}【渠道管理器】AgentExecutor 未注入！{Style.RESET_ALL}")
            return {"success": False, "error": "AgentExecutor 未初始化，请检查服务启动配置"}

        # 从 metadata 中提取 Agent 执行参数
        agent_id = message.metadata.get("agent_id")
        task = message.content   # 消息内容即任务描述
        conversation_history = message.metadata.get("conversation_history", [])

        if not agent_id:
            logger.error(f"{Fore.RED}【渠道管理器→Agent执行器】未指定 agent_id{Style.RESET_ALL}")
            return {"success": False, "error": "metadata 中未指定 agent_id"}

        # NOTE: 需要从 agent_executor 内部获取 agent_registry
        # LangGraphAgentExecutor 不直接持有 registry，需要通过独立注入或全局获取
        # 这里从 metadata 中支持直接传入 agent 对象（测试友好）或通过 registry 查询
        from app.agents.registry import AgentRegistry
        # 使用全局注册表（由 agents.py 端点在启动时初始化）
        try:
            from app.api.endpoints.agents import get_agent_registry
            agent_registry = get_agent_registry()
            agent = agent_registry.get_agent(agent_id)
        except Exception as e:
            logger.error(
                f"{Fore.RED}【渠道管理器→Agent执行器】获取 AgentRegistry 失败: {e}{Style.RESET_ALL}"
            )
            return {"success": False, "error": f"获取 AgentRegistry 失败: {e}"}

        if not agent:
            logger.error(
                f"{Fore.RED}【渠道管理器→Agent执行器】Agent 不存在: {agent_id}{Style.RESET_ALL}"
            )
            return {"success": False, "error": f"Agent 不存在: {agent_id}"}

        logger.debug(
            f"{Fore.CYAN}【渠道管理器→Agent执行器】执行 Agent: {agent_id}, "
            f"任务: {task[:50]}...{Style.RESET_ALL}"
        )

        result = await self._agent_executor.execute(
            agent=agent,
            task=task,
            conversation_history=conversation_history
        )

        logger.info(
            f"{Fore.GREEN}【渠道管理器→Agent执行器】Agent 执行完成, "
            f"success={result.get('success')}{Style.RESET_ALL}"
        )
        return result

    async def _dispatch_to_automation(self, message: ChannelMessage) -> Dict[str, Any]:
        """
        分发到自动化服务 (AutomationService)

        根据 metadata 中的 automation_type 决定调用哪个自动化方法：
          - "data_processing"    → data_processing()
          - "report_generation"  → report_generation()
          - "code_generation"    → code_generation()（默认）

        Args:
            message: 标准化消息

        Returns:
            AutomationService 对应方法的返回结果
        """
        logger.info(
            f"{Fore.CYAN}【渠道管理器→自动化服务】处理自动化请求, "
            f"sender={message.sender_id}{Style.RESET_ALL}"
        )

        if not self._automation_service:
            logger.error(f"{Fore.RED}【渠道管理器】AutomationService 未注入！{Style.RESET_ALL}")
            return {"success": False, "error": "AutomationService 未初始化，请检查服务启动配置"}

        # 从 metadata 中读取自动化类型
        automation_type = message.metadata.get("automation_type", "code_generation")

        logger.debug(
            f"{Fore.CYAN}【渠道管理器→自动化服务】automation_type={automation_type}{Style.RESET_ALL}"
        )

        # ── 数据处理 ─────────────────────────────────────────────
        if automation_type == "data_processing":
            processing_config = message.metadata.get("processing_config", {})
            return await self._automation_service.data_processing(
                data=message.content,
                processing_config=processing_config
            )

        # ── 报告生成 ─────────────────────────────────────────────
        elif automation_type == "report_generation":
            template = message.metadata.get("template")
            report_config = message.metadata.get("report_config", {})
            return await self._automation_service.report_generation(
                data_source=message.content,
                template=template,
                report_config=report_config
            )

        # ── 代码生成（默认）─────────────────────────────────────
        else:
            language = message.metadata.get("language", "Python")
            framework = message.metadata.get("framework")
            code_config = message.metadata.get("code_config", {})
            return await self._automation_service.code_generation(
                requirements=message.content,
                language=language,
                framework=framework,
                code_config=code_config
            )


# =============================================================================
# 全局单例（main.py 启动阶段初始化，各模块通过此函数获取）
# =============================================================================

_channel_manager: Optional[ChannelManager] = None


def get_channel_manager() -> ChannelManager:
    """
    获取全局 ChannelManager 单例

    第一次调用时自动创建实例。
    服务依赖由 main.py 的 lifespan 通过 set_services() 注入。

    Returns:
        ChannelManager 实例
    """
    global _channel_manager
    if _channel_manager is None:
        logger.info(f"{Fore.BLUE}【渠道管理器】首次创建 ChannelManager 全局单例{Style.RESET_ALL}")
        _channel_manager = ChannelManager()
    return _channel_manager
