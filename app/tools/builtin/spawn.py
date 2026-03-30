"""
子 Agent 任务委派工具（Spawn Tool）模块

本模块实现了 SpawnAgentTool 类，允许 LLM 在执行步骤中通过工具调用
将子任务委派给已注册的子 Agent 异步执行，并等待其结果返回。

核心设计：
- 参考 app/tools/example/spawn.py 的 SpawnTool 概念
- 包装本项目 ChildAgentManager.delegate_task 接口
- 让主 Agent（如 cs_master）在执行阶段能够在工具层面触发子 Agent 委派
- 支持流式 SSE 事件透传（sub_agent_start / sub_agent_end / 子 Agent 内部事件）

使用场景：
- 主 Agent 规划完成后，在执行器中调用 spawn_agent 工具委派子 Agent
- 子 Agent（order_agent / refund_agent / general_agent）并行或串行完成专业子任务
- 子 Agent 结果自动聚合返回给主 Agent 进行最终整合

注意事项：
- SpawnAgentTool 不在 register_all_builtin_tools 中自动注册，
  因为它需要注入 ChildAgentManager 实例（运行时依赖）
- 由 LangGraphAgentExecutor 在创建执行器时按需注入并注册到 ToolHub

参考来源：
- app/tools/example/spawn.py 的 SpawnTool 接口设计
- app/agents/child_agent_manager.py 的 ChildAgentManager.delegate_task 实现
"""

import json
from typing import Any, Dict, List, Optional, Callable, TYPE_CHECKING

from colorama import Fore, Style
from loguru import logger

from app.tools.base import Tool, ToolSchema

if TYPE_CHECKING:
    # 避免循环导入：仅类型检查时导入
    from app.agents.child_agent_manager import ChildAgentManager


class SpawnAgentTool(Tool):
    """
    子 Agent 任务委派工具

    参考 app/tools/example/spawn.py 的 SpawnTool 设计，结合本项目
    ChildAgentManager.delegate_task 接口实现，允许 LLM 在执行步骤中
    通过工具调用将任务委派给指定的子 Agent 执行。

    planning_safe = False：
        派生子 Agent 会启动新的任务执行链路，产生不确定的外部副作用，
        且子 Agent 的执行结果需要 Reflection 引擎完整观察，
        必须在 Execution Node 内执行。

    工作流程：
    1. LLM 在规划/执行阶段决定将某个子任务委派给子 Agent
    2. 调用 spawn_agent 工具，传入 agent_id 和 task 描述
    3. SpawnAgentTool 调用 ChildAgentManager.delegate_task
    4. 子 Agent 启动执行（流式事件通过 stream_callback 透传到前端）
    5. 等待子 Agent 执行完成，返回结构化结果

    属性：
        name:        工具名称，固定为 "spawn_agent"
        description: 工具描述（Contains 可委派的子 Agent 列表）
    """

    # 有副作用——启动子 Agent 任务链路，禁止在 Planning tool-calling loop 中调用
    planning_safe: bool = False

    def __init__(
        self,
        child_agent_manager: "ChildAgentManager",
        parent_agent_id: Optional[str] = None,
        stream_callback: Optional[Callable] = None,
        pending_confirmations: Optional[Dict[str, Any]] = None,
        pending_user_inputs: Optional[Dict[str, Any]] = None,
        user_rejected_tools: Optional[List[str]] = None,
    ):
        """
        初始化 SpawnAgentTool

        Args:
            child_agent_manager:  ChildAgentManager 实例（运行时注入，不可为空）
            parent_agent_id:      调用方（父 Agent）的 ID，用于循环依赖检测
            stream_callback:      父级 SSE 流式回调，子 Agent 事件会透传给前端
            pending_confirmations: 父级挂起确认映射表，子 Agent 共用同一张表
            pending_user_inputs:   父级挂起用户输入映射表，子 Agent 共用同一张表（/agents/input 能找到）
            user_rejected_tools:  父级已拒绝的工具列表，子 Agent 回避使用
        """
        if child_agent_manager is None:
            raise ValueError("SpawnAgentTool 需要注入有效的 ChildAgentManager 实例")

        self._manager               = child_agent_manager
        self._parent_agent_id       = parent_agent_id
        self._stream_callback       = stream_callback
        self._pending_confirmations = pending_confirmations
        self._pending_user_inputs   = pending_user_inputs
        self._user_rejected_tools   = user_rejected_tools or []

        # 构建可用子 Agent 列表（用于工具描述，帮助 LLM 选择正确的 agent_id）
        self._available_agents = self._build_available_agents_desc()

        self._name = "spawn_agent"
        self._description = (
            "将子任务委派给指定的子 Agent 执行，并等待其返回结果。"
            "适合将复杂任务拆解后分配给专业子 Agent 处理。"
            f"当前可委派的子 Agent：{self._available_agents}"
        )

        logger.info(
            f"{Fore.CYAN}[SpawnAgentTool] 初始化完成 "
            f"| 父Agent={parent_agent_id} "
            f"| 流式回调={'已注入' if stream_callback else '无'} "
            f"| 可委派Agent={self._available_agents}{Style.RESET_ALL}"
        )

    def _build_available_agents_desc(self) -> str:
        """
        从 AgentRegistry 读取所有已注册的 Agent，构建可委派列表描述字符串。

        NOTE: 此列表动态生成，确保与注册表中的实际 Agent 保持同步，
              避免硬编码导致 LLM 选择不存在的 agent_id。

        Returns:
            str: 形如 "order_agent(订单专员) / refund_agent(退款专员) / general_agent(通用助手)"
        """
        try:
            registry = self._manager.agent_registry
            agents   = registry.list_agents() if hasattr(registry, "list_agents") else []
            if agents:
                parts = [f"{a.agent_id}({a.name})" for a in agents]
                return " / ".join(parts)
        except Exception as e:
            logger.warning(
                f"{Fore.YELLOW}[SpawnAgentTool] 获取 Agent 列表失败: {e}，"
                f"使用默认描述{Style.RESET_ALL}"
            )
        # 降级描述（注册表读取失败时兜底）
        return "order_agent / refund_agent / general_agent"

    def update_context(
        self,
        stream_callback: Optional[Callable] = None,
        pending_confirmations: Optional[Dict[str, Any]] = None,
        pending_user_inputs: Optional[Dict[str, Any]] = None,
        user_rejected_tools: Optional[List[str]] = None,
    ) -> None:
        """
        更新运行时上下文（每次 Agent 执行前由执行引擎调用）

        NOTE: 每次新任务执行前必须重新注入最新的 stream_callback、
              pending_confirmations 和 pending_user_inputs，
              确保子 Agent 通过共享字典唤醒确认/用户输入。

        Args:
            stream_callback:      最新的 SSE 流式回调
            pending_confirmations: 最新的挂起确认字典
            pending_user_inputs:  最新的挂起用户输入字典（/agents/input 用）
            user_rejected_tools:  最新的已拒绝工具列表
        """
        if stream_callback is not None:
            self._stream_callback = stream_callback
        if pending_confirmations is not None:
            self._pending_confirmations = pending_confirmations
        if pending_user_inputs is not None:
            self._pending_user_inputs = pending_user_inputs
        if user_rejected_tools is not None:
            self._user_rejected_tools = user_rejected_tools

        logger.debug(
            f"{Fore.BLUE}[SpawnAgentTool] 运行时上下文已更新 "
            f"| stream={'已更新' if stream_callback else '未变'} "
            f"| confirmations={'已更新' if pending_confirmations else '未变'} "
            f"| user_inputs={'已更新' if pending_user_inputs else '未变'}{Style.RESET_ALL}"
        )

    @property
    def name(self) -> str:
        """获取工具名称（固定为 "spawn_agent"）"""
        return self._name

    @property
    def schema(self) -> ToolSchema:
        """
        获取工具 Schema

        参数规范：
        - agent_id: 要委派的子 Agent ID（必需），如 "order_agent"
        - task:     给子 Agent 的任务描述（必需），尽量详细包含背景信息
        - context:  补充上下文信息（可选），以字典形式传递额外数据

        Returns:
            ToolSchema: 工具参数 Schema
        """
        return ToolSchema(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type":        "string",
                        "description": (
                            f"要委派任务的子 Agent ID，必须是已注册 Agent 之一。"
                            f"可选值：{self._available_agents}"
                        )
                    },
                    "task": {
                        "type":        "string",
                        "description": (
                            "给子 Agent 的任务描述，应包含足够的背景信息和具体要求，"
                            "因为子 Agent 看不到父 Agent 的对话历史"
                        )
                    },
                    "context": {
                        "type":        "object",
                        "description": "可选的补充上下文信息（键值对），如用户 ID、订单号等",
                        "additionalProperties": True
                    }
                },
                "required":             ["agent_id", "task"],
                "additionalProperties": False
            }
        )

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行子 Agent 委派

        执行流程：
        1. 提取并验证 agent_id / task / context 参数
        2. 调用 ChildAgentManager.delegate_task 委派给子 Agent
        3. 等待子 Agent 执行完成（流式事件通过 stream_callback 透传前端）
        4. 返回结构化的子 Agent 执行结果

        Args:
            params: 参数字典，必须包含 agent_id 和 task

        Returns:
            Dict[str, Any]: 执行结果，包含：
                - success:           是否执行成功
                - agent_id:          被委派的子 Agent ID
                - agent_name:        被委派的子 Agent 名称
                - result:            子 Agent 的最终输出文本
                - step_results:      子 Agent 的分步执行结果列表
                - reflection:        子 Agent 的反思总结（若有）
                - user_rejected_tools: 子 Agent 执行中被用户拒绝的工具
                - error:             错误信息（失败时存在）
        """
        # ═══════════════ 参数提取 ═══════════════
        agent_id = params.get("agent_id", "").strip()
        task     = params.get("task",     "").strip()
        context  = params.get("context")  or {}

        # ── 非空校验 ──
        if not agent_id:
            logger.warning(
                f"{Fore.YELLOW}[SpawnAgentTool] agent_id 为空，拒绝委派{Style.RESET_ALL}"
            )
            return {"success": False, "error": "agent_id 不能为空，请指定要委派的子 Agent ID"}

        if not task:
            logger.warning(
                f"{Fore.YELLOW}[SpawnAgentTool] task 为空，拒绝委派{Style.RESET_ALL}"
            )
            return {"success": False, "error": "task 不能为空，请描述需要子 Agent 完成的任务"}

        # ── 合并 context 到任务描述（若 context 非空，附加到 task 末尾）──
        # NOTE: 子 Agent 无法看到父 Agent 历史，context 是向子 Agent 传递上下文的唯一途径
        full_task = task
        if context:
            try:
                ctx_str  = json.dumps(context, ensure_ascii=False, indent=2)
                full_task = f"{task}\n\n【补充上下文】\n{ctx_str}"
            except Exception:
                # context 序列化失败时忽略，不影响主任务
                pass

        logger.info(
            f"{Fore.CYAN}[SpawnAgentTool] 准备委派任务 "
            f"| agent_id={agent_id} "
            f"| task长度={len(full_task)}字符 "
            f"| 有流式回调={self._stream_callback is not None}{Style.RESET_ALL}"
        )
        logger.debug(
            f"{Fore.BLUE}[SpawnAgentTool] task 摘要: {full_task[:120]}...{Style.RESET_ALL}"
        )

        # ═══════════════ 委派给 ChildAgentManager ═══════════════
        try:
            result = await self._manager.delegate_task(
                parent_agent_id       = self._parent_agent_id,
                child_agent_id       = agent_id,
                task                 = full_task,
                context              = context if context else None,
                stream_callback      = self._stream_callback,
                pending_confirmations = self._pending_confirmations,
                pending_user_inputs   = self._pending_user_inputs,
                user_rejected_tools  = self._user_rejected_tools or []
            )

            if result.get("success"):
                logger.info(
                    f"{Fore.GREEN}[SpawnAgentTool] 子 Agent '{agent_id}' 执行成功 "
                    f"| result长度={len(str(result.get('result', '')))}字符{Style.RESET_ALL}"
                )
            else:
                logger.warning(
                    f"{Fore.YELLOW}[SpawnAgentTool] 子 Agent '{agent_id}' 执行失败 "
                    f"| error={result.get('error', '未知')}{Style.RESET_ALL}"
                )

            return result

        except Exception as e:
            logger.exception(
                f"{Fore.RED}[SpawnAgentTool] 委派子 Agent '{agent_id}' 时发生异常: {e}{Style.RESET_ALL}"
            )
            return {
                "success":    False,
                "error":      f"委派子 Agent 失败: {e}",
                "agent_id":   agent_id,
            }
