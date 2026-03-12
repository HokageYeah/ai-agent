"""
LangGraph Agent Executor (基于 LangGraph 的 Agent 执行器)
================================

本模块使用 LangGraph 框架实现 Agent 的状态管理和执行流程。

功能特点：
1. 使用 StateGraph 管理 Agent 状态
2. 实现 Plan -> Execute -> Reflect 循环
3. 支持条件边和状态转换
4. 集成现有的 Planning、Execution、Reflection 引擎
5. 支持流式事件输出，实时推送执行轨迹

作者: AI Agent Team
创建时间: 2026-02-15
更新时间: 2026-02-27（添加流式事件支持）
"""

import json
import time
from typing import TypedDict, Dict, List, Any, Optional, Annotated, AsyncIterator, Callable
from typing_extensions import TypedDict as TypedDictExt
from loguru import logger
from colorama import Fore, Style

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from app.agents.base import Agent
from app.agents.planning import PlanningEngine, Plan
from app.agents.execution import ExecutionEngine, ExecutionResult
from app.agents.reflection import ReflectionEngine
from app.memory.agent_run_memory import AgentRunMemory
from app.memory.session_memory import get_session_memory, extract_summary_from_run_memory
import asyncio

from app.tools.builtin.message import send_agent_message


class AgentState(TypedDict):
    """
    Agent 状态定义
    
    用于 LangGraph StateGraph 的状态管理
    """
    # 对话消息列表
    messages: Annotated[List[Dict[str, Any]], add_messages]
    # 当前执行计划
    current_plan: Optional[Plan]
    # 工具输出列表
    tool_outputs: List[Dict[str, Any]]
    # 迭代次数
    iterations: int
    # 最终结果
    final_result: Optional[Dict[str, Any]]
    # 任务描述
    task: str
    # Agent 实例
    agent: Optional[Agent]
    # NOTE: 错误上下文列表，收集本轮所有执行步骤的失败信息
    #       将传入重规划和反思 Prompt，提升 LLM 修正决策质量
    error_context: List[Dict[str, Any]]
    # NOTE: LLM 对本轮错误的分析结果（根因分析 + 修复建议）
    #       通过流式事件实时推送到前端展示
    error_analysis: Optional[Dict[str, Any]]
    # NOTE: 历次迭代的反思结论列表。
    #       每完成一次反思，将结果追加到此列表。
    #       下一轮 _plan_node 将其作为历史上下文传入规划 Prompt，
    #       防止 LLM 重复生成相同的无效计划。
    reflection_history: List[Dict[str, Any]]
    # NOTE: 等待用户确认的操作字典，key 为 confirm_id。
    #       当执行引擎遇到需要用户确认的操作（如 file_write）时，
    #       创建 asyncio.Event 并将其存入此字典，后端确认接口确认后 set 唤醒执行。
    pending_confirmations: Dict[str, Any]
    # NOTE: 等待用户输入的字典，key 为 input_request_id。
    #       当工具执行需要额外信息时（如 python_executor 需要 SMTP 配置），
    #       创建 asyncio.Event 并将其存入此字典，后端输入接口收到用户输入后 set 唤醒执行。
    pending_user_inputs: Dict[str, Any]
    # NOTE: 用户「拒绝」过的工具名称集合（如 ["file_write"]）。
    #       在 _execute_node 中记录，在 _reflect_node 中从 available_tools
    #       里过滤掉这些工具，防止反思阶段 LLM 通过 tool_gateway 绕过用户确认直接调用。
    user_rejected_tools: List[str]
    # NOTE: AgentRunMemory 实例 —— 本次任务运行的完整行为记忆仓库。
    #       以 OpenAI messages 格式存储每一轮的计划、工具调用、反思、用户操作等。
    #       Plan/Execute/Reflect 三个节点均从此处读取历史记忆并写入新记录。
    run_memory: Optional[AgentRunMemory]


# 流式事件回调函数类型
StreamCallback = Optional[Callable[[Dict[str, Any]], None]]


class LangGraphAgentExecutor:
    """
    基于 LangGraph 的 Agent 执行器
    
    使用 StateGraph 管理 Agent 的执行生命周期。
    支持流式事件输出，实时推送执行轨迹到前端。
    """
    
    def __init__(
        self,
        llm_hub,
        tool_hub,
        skill_manager,
        child_agent_manager=None,
        max_iterations: int = 5,
        tool_gateway=None
    ):
        """
        初始化 LangGraph Agent 执行器
        
        Args:
            llm_hub: LLM Hub 实例
            tool_hub: 工具中心
            skill_manager: 技能管理器
            child_agent_manager: 子 Agent 管理器（可选）
            max_iterations: 最大迭代次数
            tool_gateway: ToolCallingGateway 实例（可选）
                         传入后会注入给 ExecutionEngine，使所有工具调用
                         统一通过网关执行（带参数校验、超时控制、统计监控）
        """
        self.llm_hub = llm_hub
        self.tool_hub = tool_hub
        self.skill_manager = skill_manager
        self.child_agent_manager = child_agent_manager
        self.max_iterations = max_iterations
        self.tool_gateway = tool_gateway
        
        # 创建各个引擎
        self.planning_engine = PlanningEngine(llm_hub=llm_hub, tool_hub=tool_hub)
        self.execution_engine = ExecutionEngine(
            tool_hub=tool_hub,
            skill_manager=skill_manager,
            llm_hub=llm_hub,
            child_agent_manager=child_agent_manager,
            # 把网关注入执行引擎，使 _execute_tool() 优先走网关路径
            tool_gateway=tool_gateway
        )
        self.reflection_engine = ReflectionEngine(llm_hub=llm_hub, tool_hub=tool_hub)
        
        # 构建状态图
        self.graph = self._build_graph()

        # NOTE: 进程内用户确认映射表，key=confirm_id，value={"event": asyncio.Event, "action": str | None}
        # 后端 confirm 接口收到用户确认后，写入 action 并 set event，唤醒挂起的执行节点
        # HACK: 单进程开发环境适用；多实例部署时需改用 Redis 或其他分布式机制
        self._pending_confirmations: Dict[str, Dict[str, Any]] = {}

        # NOTE: 进程内用户输入请求映射表，key=input_request_id，value={"event": asyncio.Event, "inputs": dict | None}
        # 后端 input 接口收到用户输入后，写入 inputs 并 set event，唤醒挂起的执行节点
        self._pending_user_inputs: Dict[str, Dict[str, Any]] = {}

        gateway_status = "已启用" if tool_gateway else "未配置"
        logger.info(
            f"{Fore.GREEN}LangGraph Agent 执行器初始化完成 "
            f"[工具网关: {gateway_status}]{Style.RESET_ALL}"
        )
    
    def _create_stream_event(
        self,
        event_type: str,
        iteration: int = 0,
        step_index: Optional[int] = None,
        step_total: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        创建流式事件数据 (统一封装为 agent_message 格式)
        
        Args:
            event_type: 事件类型，将作为 progress.stage
            iteration: 当前迭代次数
            step_index: 当前步骤索引
            step_total: 步骤总数
            data: 事件数据
            error: 错误信息
            
        Returns:
            Dict[str, Any]: 统一的 agent_message 事件数据字典
        """
        import uuid
        message_id = str(uuid.uuid4())
        
        message_data = {
            "message_id": message_id,
            "message_type": "progress",
            "content": f"系统事件: {event_type}",
            "importance": "normal",
            "progress": {
                "stage": event_type,
                "iteration": iteration
            }
        }
        
        if step_index is not None:
            message_data["progress"]["step_index"] = step_index
        if step_total is not None:
            message_data["progress"]["total"] = step_total
        if data is not None:
            message_data.update(data)
        if error is not None:
            message_data["error"] = error
            
        return {
            "event": "agent_message",
            "timestamp": time.time() * 1000,
            "iteration": iteration,
            "data": message_data
        }
    
    async def _emit_stream_event(
        self,
        stream_callback: Optional[Callable],
        event_type: str,
        iteration: int = 0,
        step_index: Optional[int] = None,
        step_total: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ):
        """
        发送流式事件到回调函数（支持同步和异步回调）

        Args:
            stream_callback: 流式回调函数
            event_type: 事件类型
            iteration: 当前迭代次数
            step_index: 当前步骤索引
            step_total: 步骤总数
            data: 事件数据
            error: 错误信息
        """
        if stream_callback is None:
            return

        event = self._create_stream_event(
            event_type=event_type,
            iteration=iteration,
            step_index=step_index,
            step_total=step_total,
            data=data,
            error=error
        )

        try:
            # 检查回调是否为异步函数
            if asyncio.iscoroutinefunction(stream_callback):
                await stream_callback(event)
            else:
                stream_callback(event)
        except Exception as e:
            # 流式回调出错不影响主流程，只记录日志
            logger.warning(
                f"{Fore.YELLOW}[流式事件] 发送事件失败: {e}{Style.RESET_ALL}"
            )

    def _emit_stream_event_sync(
        self,
        stream_callback: Optional[Callable],
        event_type: str,
        iteration: int = 0,
        step_index: Optional[int] = None,
        step_total: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ):
        """
        同步版本的发送流式事件（在同步节点函数中使用）
        通过 asyncio.get_event_loop() 在同步环境中调用异步回调

        Args:
            stream_callback: 流式回调函数
            event_type: 事件类型
            iteration: 当前迭代次数
            step_index: 当前步骤索引
            step_total: 步骤总数
            data: 事件数据
            error: 错误信息
        """
        if stream_callback is None:
            return

        event = self._create_stream_event(
            event_type=event_type,
            iteration=iteration,
            step_index=step_index,
            step_total=step_total,
            data=data,
            error=error
        )

        try:
            # 检查回调是否为异步函数
            if asyncio.iscoroutinefunction(stream_callback):
                # 在同步环境中调用异步回调
                try:
                    loop = asyncio.get_running_loop()
                    # 如果已经有运行中的循环，创建一个任务
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        future = pool.submit(
                            asyncio.run,
                            stream_callback(event)
                        )
                        future.result()
                except RuntimeError:
                    # 没有运行中的循环，可以直接创建新循环
                    asyncio.run(stream_callback(event))
            else:
                stream_callback(event)
        except Exception as e:
            # 流式回调出错不影响主流程，只记录日志
            logger.warning(
                f"{Fore.YELLOW}[流式事件] 发送事件失败: {e}{Style.RESET_ALL}"
            )

    def _build_graph(self, stream_callback: Optional[Callable] = None) -> StateGraph:
        """
        构建 LangGraph 状态图
        
        定义节点、边和条件边
        
        Args:
            stream_callback: 流式事件回调函数（可选）
            
        Returns:
            StateGraph: 编译后的状态图
        """
        logger.info(f"{Fore.BLUE}构建 LangGraph 状态图{Style.RESET_ALL}")
        
        # 创建状态图
        workflow = StateGraph(AgentState)
        
        # 创建带有流式回调的异步节点包装函数
        async def plan_node_wrapper(state: AgentState) -> AgentState:
            """包装规划节点，添加流式回调支持"""
            return await self._plan_node(state, stream_callback)
        
        async def execute_node_wrapper(state: AgentState) -> AgentState:
            """包装执行节点，添加流式回调支持"""
            return await self._execute_node(state, stream_callback)
        
        async def reflect_node_wrapper(state: AgentState) -> AgentState:
            """包装反思节点，添加流式回调支持"""
            return await self._reflect_node(state, stream_callback)
        
        # 添加节点
        workflow.add_node("plan", plan_node_wrapper)
        workflow.add_node("execute", execute_node_wrapper)
        workflow.add_node("reflect", reflect_node_wrapper)
        
        # 设置入口点
        workflow.set_entry_point("plan")
        
        # 添加固定边
        workflow.add_edge("plan", "execute")
        workflow.add_edge("execute", "reflect")
        
        # 添加条件边
        workflow.add_conditional_edges(
            "reflect",
            self._should_continue,
            {
                "continue": "plan",  # 需要继续迭代
                "end": END  # 结束执行
            }
        )
        
        # 编译图
        compiled_graph = workflow.compile()
        
        logger.info(f"{Fore.GREEN}状态图构建完成{Style.RESET_ALL}")
        
        return compiled_graph
    
    async def _plan_node(
        self, 
        state: AgentState,
        stream_callback: Optional[Callable] = None
    ) -> AgentState:
        """
        规划节点
        
        调用 PlanningEngine 创建执行计划
        
        Args:
            state: 当前状态
            stream_callback: 流式事件回调函数
            
        Returns:
            AgentState: 更新后的状态
        """
        iteration = state.get("iterations", 0)
        logger.info(f"{Fore.BLUE}[Plan Node] 开始规划 (迭代 {iteration}){Style.RESET_ALL}")
        
        # 发送开始规划事件
        await send_agent_message(
            stream_callback=stream_callback,
            message_type="progress",
            content="Agent 正在分析任务并制定执行计划...",
            progress={"stage": "plan_start", "iteration": iteration}
        )
        
        agent = state["agent"]
        task = state["task"]
        user_rejected_tools: List[str] = state.get("user_rejected_tools", []) or []
        
        # 按 Agent 的授权列表过滤工具和技能
        # agent.available_tools 为空列表时表示不限制（向后兼容），否则只暴露授权项
        if self.tool_hub:
            all_tools = self.tool_hub.list_tools()
            if agent.available_tools:
                available_tools = [t for t in all_tools if t.name in agent.available_tools]
                restricted = [t.name for t in all_tools if t.name not in agent.available_tools]
                if restricted:
                    logger.debug(
                        f"{Fore.YELLOW}[Plan Node] Agent '{agent.name}' "
                        f"不可访问工具: {restricted}{Style.RESET_ALL}"
                    )
            else:
                available_tools = all_tools
        else:
            available_tools = []

        # NOTE: 规划阶段同样要排除用户已拒绝的工具，防止下一轮继续重复规划同一敏感操作
        # （例如用户拒绝 file_write 后，后续迭代应优先寻找替代方案，而非再次触发确认）
        if user_rejected_tools and available_tools:
            before_count = len(available_tools)
            available_tools = [t for t in available_tools if t.name not in user_rejected_tools]
            logger.info(
                f"{Fore.YELLOW}[Plan Node] 已排除用户拒绝工具: {user_rejected_tools}，"
                f"可用工具 {before_count}->{len(available_tools)}{Style.RESET_ALL}"
            )

        if self.skill_manager:
            all_skills = self.skill_manager.list_skills()
            if agent.available_skills:
                available_skills = [s for s in all_skills if s.skill_id in agent.available_skills]
            else:
                available_skills = all_skills
        else:
            available_skills = []

        logger.info(
            f"{Fore.BLUE}[Plan Node] Agent '{agent.name}' "
            f"可用工具: {[t.name for t in available_tools]} | "
            f"可用技能: {[s.skill_id for s in available_skills]}{Style.RESET_ALL}"
        )
        
        # NOTE: 如果是重规划场景（迭代 > 0 且有错误上下文），将错误信息传入规划引擎
        # 使 LLM 在重规划时能规避已知失败路径
        current_error_ctx = state.get("error_context", [])
        if current_error_ctx:
            logger.info(
                f"{Fore.YELLOW}[Plan Node] 检测到 {len(current_error_ctx)} 条错误上下文，"
                f"本次为错误感知重规划{Style.RESET_ALL}"
            )

        # NOTE: 传入历史反思记录，使 LLM 能从之前的失败中学习改进策略。
        # 这是解决「无效迭代循环」的核心修复点：
        # 如果 error_context 为空（步骤技术成功但任务未达成），reflection_history
        # 仍存储了之前轮次的 feedback，能指引 LLM 调整方向或明确告知用户无法完成。
        current_reflection_history = state.get("reflection_history", [])
        if current_reflection_history:
            logger.info(
                f"{Fore.YELLOW}[Plan Node] 携带 {len(current_reflection_history)} 条历史反思记录，"
                f"本次为历史感知重规划{Style.RESET_ALL}"
            )

        # NOTE: 为跨迭代规划注入“上一轮执行记忆”，避免每轮重复走相同查询路径。
        # 包含：上一轮计划、上一轮执行步骤结果、上一轮最终结果、用户拒绝工具。
        # 这是解决“第二轮仍重复委派 order_agent 查询同一订单”的关键上下文。
        planning_context: Dict[str, Any] = {
            "iteration": iteration,
            "user_rejected_tools": user_rejected_tools,
        }
        # 取最近一次 plan/execution 消息，控制体积只保留近一次
        recent_messages = state.get("messages", []) or []
        # NOTE: state["messages"] 可能混入 LangChain BaseMessage（如 SystemMessage）对象，
        #       这些对象没有 .get 方法。这里仅提取我们自己追加的 dict 结构消息。
        dict_messages = [m for m in recent_messages if isinstance(m, dict)]
        last_plan_msg = next((m for m in reversed(dict_messages) if m.get("type") == "plan"), None)
        last_exec_msg = next((m for m in reversed(dict_messages) if m.get("type") == "execution"), None)
        if last_plan_msg:
            planning_context["last_plan"] = {
                "reasoning": last_plan_msg.get("reasoning", ""),
                "steps": last_plan_msg.get("steps", [])[:8]
            }
        if last_exec_msg:
            planning_context["last_execution"] = {
                "content": last_exec_msg.get("content", ""),
                # 仅保留最近步骤，避免 Prompt 爆长
                "step_results": (last_exec_msg.get("step_results", []) or [])[-6:]
            }
        if state.get("final_result") is not None:
            planning_context["last_final_result"] = state.get("final_result")

        # 创建计划（优先使用 run_memory messages 格式，传入 run_memory 时旧的文字拼接自动降级）
        plan = await self.planning_engine.create_plan(
            agent=agent,
            task=task,
            available_tools=available_tools,
            available_skills=available_skills,
            context=planning_context,
            error_context=current_error_ctx if current_error_ctx else None,
            reflection_history=current_reflection_history if current_reflection_history else None,
            # NOTE: 传入 run_memory，优先使用 messages 格式传递历史执行记忆
            run_memory=state.get("run_memory"),
            iteration=iteration
        )
        
        logger.info(f"{Fore.GREEN}[Plan Node] 计划创建完成{Style.RESET_ALL}")
        
        # 发送规划完成事件（含推理过程和步骤列表）
        await send_agent_message(
            stream_callback=stream_callback,
            message_type="progress",
            content="规划完成",
            progress={"stage": "plan_complete", "iteration": iteration},
            extra_data={
                "reasoning": plan.reasoning,
                "steps": [step.to_dict() for step in plan.steps]
            }
        )
        
        # 更新状态
        state["current_plan"] = plan
        state["messages"].append({
            "role": "system",
            "type": "plan",
            "content": f"Created plan with {len(plan.steps)} steps",
            "reasoning": plan.reasoning,
            "steps": [step.to_dict() for step in plan.steps]
        })

        # NOTE: 重规划后清空上一轮的错误分析结果（错误已被 LLM 考虑到新计划中）
        # 保留 error_context 以便后续迭代中继续累积错误历史
        state["error_analysis"] = None

        # NOTE: 规划完成后，将计划产出写入 run_memory（以 assistant 消息格式）
        #       这样下一轮规划时 LLM 能在 messages 数组中看到历史计划内容
        run_memory: Optional[AgentRunMemory] = state.get("run_memory")
        if run_memory is not None:
            run_memory.write_plan(
                iteration=iteration,
                reasoning=plan.reasoning,
                steps=[step.to_dict() for step in plan.steps]
            )
            logger.info(
                f"{Fore.CYAN}[记忆写入] 规划产出已写入 run_memory, "
                f"iteration={iteration}, steps={len(plan.steps)}{Style.RESET_ALL}"
            )
        
        return state
    
    async def _execute_node(
        self, 
        state: AgentState,
        stream_callback: Optional[Callable] = None
    ) -> AgentState:
        """
        执行节点
        
        调用 ExecutionEngine 执行计划
        
        Args:
            state: 当前状态
            stream_callback: 流式事件回调函数
            
        Returns:
            AgentState: 更新后的状态
        """
        iteration = state.get("iterations", 0)
        logger.info(f"{Fore.BLUE}[Execute Node] 开始执行计划 (迭代 {iteration}){Style.RESET_ALL}")
        
        agent = state["agent"]
        plan = state["current_plan"]
        
        # 获取步骤总数
        step_total = len(plan.steps) if plan and plan.steps else 0
        
        # 发送开始执行事件（通知前端执行阶段开始）
        await send_agent_message(
            stream_callback=stream_callback,
            message_type="progress",
            content=f"开始执行 {step_total} 个计划步骤...",
            progress={"stage": "step_start", "iteration": iteration, "current": 0, "total": step_total}
        )
        
        # NOTE: 在执行计划前，扫描步骤是否包含需要用户确认的操作（目前仅 file_write）。
        # 若包含，则先推送 user_confirm_required 事件，挂起等待用户确认/拒绝后再执行。
        # 这是用户确认交互机制的核心入口。
        TOOLS_REQUIRING_CONFIRM = {"file_write"}  # 可扩展：如 email_send、shell_exec 等

        def _extract_tool_name_for_confirm(step) -> str:
            """
            统一提取需要确认判断用的工具名，兼容两类规划输出：
            1) 标准格式: {"action":"tool","tool_name":"file_write",...}
            2) 兼容格式: {"action":"file_write","tool_name":"file_write",...}
               （执行引擎后续会自动纠正为 action='tool'）
            """
            action_name = (getattr(step, "action", "") or "").strip()
            params_tool = (getattr(step, "params", {}) or {}).get("tool_name", "")
            params_tool = params_tool.strip() if isinstance(params_tool, str) else ""

            if action_name == "tool":
                return params_tool
            # 兼容：若 action 直接是某个危险工具名，也应触发确认
            if action_name in TOOLS_REQUIRING_CONFIRM:
                return action_name
            # 兜底：非 tool action 但 params.tool_name 命中危险工具时，也要求确认
            if params_tool in TOOLS_REQUIRING_CONFIRM:
                return params_tool
            return ""

        confirm_required_steps = [
            step for step in (plan.steps or [])
            if _extract_tool_name_for_confirm(step) in TOOLS_REQUIRING_CONFIRM
        ] if plan else []

        if confirm_required_steps and stream_callback:
            import uuid
            for step in confirm_required_steps:
                tool_name = _extract_tool_name_for_confirm(step) or step.params.get("tool_name", "file_write")
                tool_params = {k: v for k, v in step.params.items() if k != "tool_name"}

                import json
                params_str = json.dumps(tool_params, ensure_ascii=False, indent=2)
                
                # 推送待确认事件到前端（采用统一 agent_message 格式）
                confirm_id = await send_agent_message(
                    stream_callback=stream_callback,
                    message_type="confirm",
                    content=f"Agent 计划执行危险操作 **{tool_name}**，即将传入的参数如下：\n```json\n{params_str}\n```\n请确认是否继续？",
                    importance="high",
                    confirm_action=f"执行 {tool_name}"
                )

                logger.info(
                    f"{Fore.YELLOW}[Execute Node] 检测到需要用户确认的操作: {tool_name}，"
                    f"confirm_id={confirm_id}{Style.RESET_ALL}"
                )

                # 创建 asyncio.Event，挂起等待用户确认（最多 300 秒超时）
                confirm_event = asyncio.Event()
                self._pending_confirmations[confirm_id] = {
                    "event": confirm_event,
                    "action": None  # "confirm" / "reject"，由后端接口写入
                }

                try:
                    await asyncio.wait_for(confirm_event.wait(), timeout=300)
                    action = self._pending_confirmations[confirm_id].get("action", "reject")
                except asyncio.TimeoutError:
                    action = "reject"
                    logger.warning(
                        f"{Fore.YELLOW}[Execute Node] 用户确认超时（confirm_id={confirm_id}），默认拒绝{Style.RESET_ALL}"
                    )
                finally:
                    self._pending_confirmations.pop(confirm_id, None)

                # 推送用户确认结果事件到前端
                await send_agent_message(
                    stream_callback=stream_callback,
                    message_type="progress",
                    content="用户已确认" if action == "confirm" else "用户已拒绝，跳过该操作",
                    progress={"stage": "user_confirm_result", "iteration": iteration},
                    extra_data={
                        "confirm_id": confirm_id,
                        "action": action,
                        "tool_name": tool_name,
                        "message": "用户已确认" if action == "confirm" else "用户已拒绝，跳过该操作"
                    }
                )

                # 用户拒绝时，将该步骤从计划中移除，并记录到 state["user_rejected_tools"]
                if action != "confirm":
                    logger.info(
                        f"{Fore.RED}[Execute Node] 用户拒绝执行 {tool_name}（confirm_id={confirm_id}），"
                        f"将从计划中移除该步骤，并加入 user_rejected_tools 黑名单{Style.RESET_ALL}"
                    )
                    plan.steps = [
                        s for s in plan.steps
                        if _extract_tool_name_for_confirm(s) != tool_name
                    ]

                    # NOTE: 将被拒绝的工具名加入状态，供 _reflect_node 过滤
                    #       避免反思阶段 LLM 通过 tool_gateway 绕过确认再次执行
                    current_rejected = state.get("user_rejected_tools", []) or []
                    if tool_name not in current_rejected:
                        current_rejected = current_rejected + [tool_name]
                        state["user_rejected_tools"] = current_rejected
                        logger.info(
                            f"{Fore.YELLOW}[Execute Node] 已将 '{tool_name}' 加入 user_rejected_tools，"
                            f"当前黑名单: {current_rejected}{Style.RESET_ALL}"
                        )

                    # NOTE: 将用户拒绝操作写入 error_context。
                    #       这样反思引擎的 Prompt 会包含这条记录，
                    #       LLM 才知道任务未完成是因为「用户主动拒绝」，
                    #       而不会被 execution_result.success=True 误导。
                    user_reject_record = {
                        "step_desc": f"用户拒绝执行 {tool_name}",
                        "error_msg": (
                            f"用户在确认弹窗中点击了「取消」，操作 [{tool_name}] 未被执行。"
                            f"这是用户的主动选择，任务目标（{state.get('task', '')}）尚未完成。"
                        ),
                        "error_type": "UserRejected",
                        "suggestion": (
                            f"用户明确拒绝了 [{tool_name}] 操作。"
                            "请在最终答案中如实告知用户操作已被取消，"
                            "不要重新尝试同一操作，也不要声称任务已成功完成。"
                        ),
                        "iteration": iteration
                    }
                    current_err_ctx = state.get("error_context", []) or []
                    state["error_context"] = current_err_ctx + [user_reject_record]
                    logger.info(
                        f"{Fore.YELLOW}[Execute Node] 已将用户拒绝记录写入 error_context，"
                        f"供反思引擎感知真实结果{Style.RESET_ALL}"
                    )

                    # NOTE: 同步更新 final_answer 步骤的内容，使其反映实际情况
                    #       否则预设的"已成功写入"文案会被当作执行结果传给反思 LLM
                    for step in plan.steps:
                        if step.action == "final_answer":
                            step.content = (
                                f"用户取消了 [{tool_name}] 操作，该操作未执行。"
                                f"任务目标（{state.get('task', '')}）未能完成，"
                                "请如实告知用户操作已被取消。"
                            )
                            logger.info(
                                f"{Fore.YELLOW}[Execute Node] 已更新 final_answer 内容以反映用户拒绝结果{Style.RESET_ALL}"
                            )
                            break

                    # NOTE: 将用户拒绝行为写入 run_memory（以 user 消息格式记录）
                    #       这样反思/重规划时，LLM 在 messages 数组中能直接看到用户的操作
                    run_memory_ref: Optional[AgentRunMemory] = state.get("run_memory")
                    if run_memory_ref is not None:
                        run_memory_ref.write_user_action(
                            iteration=iteration,
                            action="reject",
                            tool_name=tool_name
                        )
                        logger.info(
                            f"{Fore.CYAN}[记忆写入] 用户拒绝操作已写入 run_memory: "
                            f"tool={tool_name}, iteration={iteration}{Style.RESET_ALL}"
                        )

        # 执行计划
        # 把 task、stream_callback、pending_confirmations 一起放入 context，
        # 以便执行引擎在委派子 Agent 时能透传流式回调和挂起确认映射表，
        # 从而支持子 Agent 内部触发的用户确认弹窗通过同一 SSE 流推送到前端
        
        # 从 run_memory 中获取会话历史上下文消息（用于纯记忆问答兜底合成）
        # NOTE: 只有 run_memory 存在时才有 context_messages，否则为空列表
        _run_memory_for_ctx: Optional[AgentRunMemory] = state.get("run_memory")
        _ctx_messages_for_exec = (
            _run_memory_for_ctx.context_messages
            if _run_memory_for_ctx is not None
            else []
        )
        
        # ═══════════════════════════════════════════════════════════════════════
        # 【实时步骤事件推送回调】
        #
        # 设计动机（修复事件顺序错乱问题）：
        #   原来的逻辑是：先 await execute_plan()，等所有步骤跑完，
        #   再在 _execute_node 里遍历 step_results 批量发送 tool_complete/delegate_complete。
        #   但委派子Agent时，child_agent_manager 会在 execute_plan 内部（执行期间）
        #   直接通过 stream_callback 推送 sub_agent_start/end 及子Agent全部内部事件。
        #   导致：
        #     sub_agent_start(general_agent) → [general_agent所有事件] → sub_agent_end
        #     （以上都在 execute_plan 内推送）
        #   然后 execute_plan 返回，_execute_node 才推送：
        #     tool_complete(database_query) ← ❌ 晚于 sub_agent_end 出现
        #     delegate_complete(general_agent) ← ❌ 也在最后才到达
        #
        #   修复方案：通过 on_step_complete 回调，在 execute_plan 内部每步执行完就立刻发出
        #   相应的 SSE 事件，保证 tool_complete 在 sub_agent_start 之前推送给前端。
        # ═══════════════════════════════════════════════════════════════════════
        
        # 捕获当前帧变量（避免闭包引用可能变化的外层变量）
        _iter_ref = iteration
        _step_total_ref = step_total
        _cb_ref = stream_callback

        async def _on_step_complete(step_result: Dict[str, Any], step_idx: int, total: int) -> None:
            """
            步骤完成实时回调：在 execute_plan 内每步结束后立即调用，
            向前端推送对应的 SSE 事件（tool_complete / delegate_complete / skill_complete / step_complete）。
            
            这样可以保证事件顺序与实际执行顺序完全一致：
              步骤1(database_query)完成 → tool_complete 立即推送
              步骤2(delegate)开始 → sub_agent_start（由 child_agent_manager 推送）
              ...general_agent 内部事件...
              步骤2(delegate)完成 → delegate_complete 立即推送
            """
            if not _cb_ref:
                return
            
            action = step_result.get("action", "unknown")
            logger.debug(
                f"{Fore.CYAN}[实时步骤回调] 推送步骤 {step_idx}/{total} 事件: "
                f"action={action}{Style.RESET_ALL}"
            )
            
            if action == "tool":
                # 工具调用完成事件
                await send_agent_message(
                    stream_callback=_cb_ref,
                    message_type="progress",
                    content=f"工具调用完成: {step_result.get('tool_name', 'unknown')}",
                    progress={"stage": "tool_complete", "iteration": _iter_ref, "current": step_idx, "total": total},
                    extra_data=step_result
                )
                logger.info(
                    f"{Fore.GREEN}[实时步骤回调] 工具完成事件已推送: "
                    f"tool={step_result.get('tool_name', 'unknown')}, step={step_idx}/{total}{Style.RESET_ALL}"
                )
            elif action == "delegate":
                # 子 Agent 委派完成事件
                await send_agent_message(
                    stream_callback=_cb_ref,
                    message_type="progress",
                    content=f"委派子Agent完成: {step_result.get('agent_id', 'unknown')}",
                    progress={"stage": "delegate_complete", "iteration": _iter_ref, "current": step_idx, "total": total},
                    extra_data=step_result
                )
                logger.info(
                    f"{Fore.GREEN}[实时步骤回调] 委派完成事件已推送: "
                    f"agent_id={step_result.get('agent_id', 'unknown')}, step={step_idx}/{total}{Style.RESET_ALL}"
                )
            elif action == "skill":
                # 技能调用完成事件
                await send_agent_message(
                    stream_callback=_cb_ref,
                    message_type="progress",
                    content=f"技能使用完成: {step_result.get('skill_id', 'unknown')}",
                    progress={"stage": "skill_complete", "iteration": _iter_ref, "current": step_idx, "total": total},
                    extra_data=step_result
                )
                logger.info(
                    f"{Fore.GREEN}[实时步骤回调] 技能完成事件已推送: "
                    f"skill_id={step_result.get('skill_id', 'unknown')}, step={step_idx}/{total}{Style.RESET_ALL}"
                )
            else:
                # final_answer 或其他步骤：发送 step_complete 事件
                step_action = step_result.get("action", "unknown")
                if step_action == "tool":
                    step_name = f"调用工具: {step_result.get('tool_name', 'unknown')}"
                elif step_action == "skill":
                    step_name = f"使用技能: {step_result.get('skill_id', 'unknown')}"
                elif step_action == "delegate":
                    step_name = f"委派子Agent: {step_result.get('agent_id', 'unknown')}"
                elif step_action == "final_answer":
                    step_name = "合成最终答案"
                else:
                    step_name = f"执行步骤: {step_action}"
                
                await send_agent_message(
                    stream_callback=_cb_ref,
                    message_type="progress",
                    content=f"步骤 {step_idx}/{total} 完成: {step_name}",
                    progress={"stage": "step_complete", "iteration": _iter_ref, "current": step_idx, "total": total},
                    extra_data={
                        **step_result,
                        "step_name": step_name,
                        "message": f"步骤 {step_idx}/{total} 完成: {step_name}"
                    }
                )
                logger.info(
                    f"{Fore.GREEN}[实时步骤回调] 步骤完成事件已推送: "
                    f"{step_name}, step={step_idx}/{total}{Style.RESET_ALL}"
                )
            
            # 若步骤失败，额外推送错误事件
            if not step_result.get("success", True):
                await send_agent_message(
                    stream_callback=_cb_ref,
                    message_type="progress",
                    content=f"步骤执行出错: {step_result.get('error', 'Unknown error')}",
                    progress={"stage": "step_error", "iteration": _iter_ref, "current": step_idx, "total": total},
                    extra_data={
                        "error": step_result.get("error", "Unknown error"),
                        **step_result
                    }
                )
                logger.warning(
                    f"{Fore.YELLOW}[实时步骤回调] 步骤失败事件已推送: "
                    f"step={step_idx}/{total}, error={step_result.get('error', '')[:80]}{Style.RESET_ALL}"
                )

        # 执行计划，并传入实时步骤回调（仅在有 stream_callback 时才传入，无需 SSE 时跳过）
        execution_result = await self.execution_engine.execute_plan(
            agent=agent,
            plan=plan,
            context={
                "task": state.get("task", ""),
                # 透传父级 stream_callback：子 Agent 用它推送 user_confirm_required 等事件
                "stream_callback": stream_callback,
                # 透传父级 pending_confirmations：子 Agent 把 confirm_id 注册到同一张表
                "pending_confirmations": self._pending_confirmations,
                # 透传父级 pending_user_inputs：子 Agent 把 input_request_id 注册到同一张表
                "pending_user_inputs": self._pending_user_inputs,
                # 透传用户拒绝的工具黑名单防止在子流程(如技能引擎/子Agent中)穿透
                "user_rejected_tools": state.get("user_rejected_tools", []),
                # 传入会话历史上下文消息：执行引擎在纯记忆问答场景（无工具调用）时使用，
                # 当 LLM 规划的 final_answer.content 仍是意图描述而非真实答案时，
                # 兜底利用这些历史摘要触发 LLM 合成真正的回答。
                "context_messages": _ctx_messages_for_exec,
            },
            # 实时步骤回调：每步完成后立即推送对应 SSE 事件，保证事件顺序
            on_step_complete=_on_step_complete if stream_callback else None
        )

        
        # NOTE: 关键修复 - 如果本轮包含被拒绝的操作，强制置 success 为 False，并修改 result 结果文案
        #       避免因为剩余步骤（如 final_answer）成功执行导致整体被判定为成功
        rejected_tools = [err.get("step_desc", "").replace("用户拒绝执行 ", "") for err in state.get("error_context", []) if err.get("error_type") == "UserRejected"]
        if rejected_tools:
            if execution_result.success:
                logger.info(
                    f"{Fore.YELLOW}[Execute Node] 检测到用户拒绝操作，"
                    f"强制将执行结果标记为失败 (success=False)，并替换回答文本{Style.RESET_ALL}"
                )
                execution_result.success = False
            # 始终覆盖 result 结果，确保发送给前端最后一句是明确的取消反馈
            execution_result.result = f"用户已取消操作：{', '.join(rejected_tools)}，任务未完成。"
            
        # ── 新增: 合并由于子代理引发但冒泡上来的被拒绝的工具 ────────────────────
        # 由于子 Agent 拥有自己独立的 state 字典运转流程，
        # 我们必须把子 Agent 返回结果中新被拒绝的工具，合并到当前主 Agent 的黑名单中。
        current_rejected = state.get("user_rejected_tools", []) or []
        for t in execution_result.user_rejected_tools:
            if t not in current_rejected:
                current_rejected.append(t)
        state["user_rejected_tools"] = current_rejected
        
        logger.info(
            f"{Fore.GREEN}[Execute Node] 计划执行完成，所有步骤事件已在执行过程中实时推送{Style.RESET_ALL}"
        )
        
        # 【注意】步骤级别的 SSE 事件（tool_complete/delegate_complete/skill_complete/step_complete）
        # 已通过 on_step_complete 回调在 execute_plan 执行期间实时推送，
        # 此处不再重复遍历 step_results 批量发送，避免重复事件和顺序混乱。
        
        # 更新状态
        state["tool_outputs"].extend(execution_result.step_results)
        state["messages"].append({
            "role": "system",
            "type": "execution",
            "content": f"Executed plan: success={execution_result.success}",
            "step_results": execution_result.step_results
        })
        
        # 无论执行成功或失败（如被用户拒绝），都保存在状态中供后续反思
        state["final_result"] = execution_result.to_dict()

        # NOTE: 将执行步骤的结果写入 run_memory（工具/技能/委派/最终答案各自的格式）
        #       这样反思阶段 LLM 通过 messages 数组能直接看到本轮所有工具调用及其结果
        run_memory: Optional[AgentRunMemory] = state.get("run_memory")
        if run_memory is not None and execution_result.step_results:
            for sr in execution_result.step_results:
                sr_action = sr.get("action", "unknown")
                sr_success = sr.get("success", True)
                sr_error = sr.get("error", "")

                if sr_action == "tool":
                    run_memory.write_tool_call(
                        iteration=iteration,
                        tool_name=sr.get("tool_name", "unknown"),
                        tool_args=sr.get("params", {}),
                        tool_result=sr.get("result"),
                        success=sr_success,
                        error_msg=sr_error
                    )
                elif sr_action == "skill":
                    run_memory.write_skill_call(
                        iteration=iteration,
                        skill_id=sr.get("skill_id", "unknown"),
                        skill_result=sr.get("result"),
                        success=sr_success
                    )
                elif sr_action == "delegate":
                    result_summary = str(sr.get("result", ""))
                    run_memory.write_delegate(
                        iteration=iteration,
                        child_agent_id=sr.get("agent_id", "unknown"),
                        sub_task=sr.get("task", ""),
                        result_summary=result_summary,
                        success=sr_success
                    )
                # final_answer 步骤不单独写入，已体现在 reflection 阶段

            logger.info(
                f"{Fore.CYAN}[记忆写入] 执行步骤结果已写入 run_memory: "
                f"{len(execution_result.step_results)} 条, iteration={iteration}{Style.RESET_ALL}"
            )

        # ═══════════════════════════════════════════════════════════
        # 【错误收集阶段】
        # 遇历失败的步骤自动提取，构建结构化 error_context
        # 后续传递给错误分析方法、反思引擎、下一轮规划引擎
        # ═══════════════════════════════════════════════════════════
        failed_steps = [
            sr for sr in (execution_result.step_results or [])
            if not sr.get("success", True)
        ]

        if failed_steps:
            logger.warning(
                f"{Fore.YELLOW}[错误收集] 本轮执行发现 {len(failed_steps)} 个失败步骤，"
                f"开始构建错误上下文{Style.RESET_ALL}"
            )

            # 为每个失败步骤构建结构化错误记录
            new_error_records = []
            for sr in failed_steps:
                action = sr.get("action", "unknown")
                error_msg = sr.get("error", str(sr.get("result", "")))

                # 构建描述性步骤名称
                if action == "tool":
                    step_desc = f"工具调用: {sr.get('tool_name', 'unknown')}"
                    error_type = "ToolError"
                    suggestion = f"检查工具 '{sr.get('tool_name')}' 的入参格式或权限"
                elif action == "skill":
                    step_desc = f"技能调用: {sr.get('skill_id', 'unknown')}"
                    error_type = "SkillError"
                    suggestion = f"检查技能 '{sr.get('skill_id')}' 的参数是否完整"
                elif action == "delegate":
                    step_desc = f"子Agent委派: {sr.get('agent_id', 'unknown')}"
                    error_type = "DelegateError"
                    suggestion = f"检查子Agent '{sr.get('agent_id')}' 是否已注册且可用"
                else:
                    step_desc = f"未知操作: {action}"
                    error_type = "UnknownError"
                    suggestion = "请检查操作类型是否正确"

                new_error_records.append({
                    "step_desc": step_desc,
                    "error_msg": error_msg,
                    "error_type": error_type,
                    "suggestion": suggestion,
                    "iteration": iteration
                })

                logger.debug(
                    f"{Fore.RED}[错误收集] {step_desc} 失败: {error_msg[:100]}{Style.RESET_ALL}"
                )

            # 将本轮错误累加到 error_context（践代累积历史错误）
            current_error_ctx = state.get("error_context", []) or []
            current_error_ctx.extend(new_error_records)
            state["error_context"] = current_error_ctx

            logger.info(
                f"{Fore.YELLOW}[错误收集] error_context 已更新，"
                f"当前共有 {len(current_error_ctx)} 条错误记录{Style.RESET_ALL}"
            )

            # 发送错误分析开始事件（采用统一格式）
            await send_agent_message(
                stream_callback=stream_callback,
                message_type="progress",
                content=f"检测到 {len(failed_steps)} 个步骤失败，Agent 正在分析错误根因并制定修复方案...",
                progress={"stage": "error_analysis_start", "iteration": iteration, "failed_count": len(failed_steps)}
            )

            # 调用 LLM 分析错误并将结果通过流式事件推送
            error_analysis_result = await self._analyze_errors(
                agent=state["agent"],
                task=state["task"],
                error_context=new_error_records,
                stream_callback=stream_callback,
                iteration=iteration
            )

            # 将错误分析结果写入状态（下一步可供反思引擎参考）
            state["error_analysis"] = error_analysis_result
        else:
            # 本轮无失败步骤，保持 error_context 不变（可能有历史错误）
            logger.info(
                f"{Fore.GREEN}[错误收集] 本轮所有步骤均成功，无新增错误{Style.RESET_ALL}"
            )
        
        # 发送整个执行阶段完成事件，添加步骤摘要信息
        # 构建步骤摘要列表
        step_summary_list = []
        if execution_result.step_results:
            for i, sr in enumerate(execution_result.step_results, 1):
                action = sr.get("action", "unknown")
                if action == "tool":
                    step_summary_list.append(f"{i}. 工具: {sr.get('tool_name', 'unknown')}")
                elif action == "skill":
                    step_summary_list.append(f"{i}. 技能: {sr.get('skill_id', 'unknown')}")
                elif action == "delegate":
                    step_summary_list.append(f"{i}. 委派: {sr.get('agent_id', 'unknown')}")
                elif action == "final_answer":
                    step_summary_list.append(f"{i}. 合成答案")
                else:
                    step_summary_list.append(f"{i}. {action}")
        
        step_summary = "\n".join(step_summary_list) if step_summary_list else "无"
        
        await send_agent_message(
            stream_callback=stream_callback,
            message_type="progress",
            content="所有步骤执行完毕，准备进入反思阶段",
            progress={"stage": "execute_complete", "iteration": iteration, "current": step_total, "total": step_total},
            extra_data={
                "success": execution_result.success,
                "message": "所有步骤执行完毕，准备进入反思阶段",
                "step_summary": step_summary_list,
                "steps_count": len(execution_result.step_results) if execution_result.step_results else 0
            }
        )
        
        return state
    
    async def _reflect_node(
        self, 
        state: AgentState,
        stream_callback: Optional[Callable] = None
    ) -> AgentState:
        """
        反思节点
        
        调用 ReflectionEngine 评估执行结果
        
        Args:
            state: 当前状态
            stream_callback: 流式事件回调函数
            
        Returns:
            AgentState: 更新后的状态
        """
        iteration = state.get("iterations", 0)
        logger.info(f"{Fore.BLUE}[Reflect Node] 开始反思 (迭代 {iteration}){Style.RESET_ALL}")
        
        # 发送开始反思事件（通知前端进入自我反思阶段）
        await send_agent_message(
            stream_callback=stream_callback,
            message_type="progress",
            content="Agent 正在评估执行结果...",
            progress={"stage": "reflection_start", "iteration": iteration}
        )
        
        agent = state["agent"]
        task = state["task"]
        final_result = state.get("final_result")

        if not final_result:
            logger.warning(f"{Fore.YELLOW}[Reflect Node] 没有执行结果，跳过反思{Style.RESET_ALL}")
            state["messages"].append({
                "role": "system",
                "type": "reflection",
                "content": "No execution result to reflect on"
            })
            
            # 发送反思完成事件（无结果时跳过反思）
            await send_agent_message(
                stream_callback=stream_callback,
                message_type="progress",
                content="无执行结果，跳过反思",
                progress={"stage": "reflection_complete", "iteration": iteration},
                extra_data={"skipped": True, "message": "无执行结果，跳过反思"}
            )
            return state
        
        # 将字典转换为 ExecutionResult 对象
        # 注意：需要过滤掉可能存在的额外字段（如之前的 reflection）
        execution_result_args = {
            k: v for k, v in final_result.items() 
            if k in ["success", "result", "step_results", "error"]
        }
        execution_result_obj = ExecutionResult(**execution_result_args)
        
        # 反思执行结果（携带 error_context 提升反思质量）
        current_error_ctx = state.get("error_context", []) or []
        if current_error_ctx:
            logger.info(
                f"{Fore.YELLOW}[Reflect Node] 携带 {len(current_error_ctx)} 条错误信息进行反思{Style.RESET_ALL}"
            )

        # 复用 _plan_node 的工具过滤逻辑，确保反思阶段 LLM 只看到授权工具
        # NOTE: 同时排除用户已拒绝过的工具（user_rejected_tools），
        #       防止反思 LLM 通过 tool_gateway 绕过用户确认直接调用被拒绝操作。
        #       例如：用户拒绝了 file_write → 反思阶段不应再看到 file_write 的工具定义。
        user_rejected_tools: List[str] = state.get("user_rejected_tools", []) or []
        if user_rejected_tools:
            logger.info(
                f"{Fore.YELLOW}[Reflect Node] 当前会话中用户拒绝过的工具: {user_rejected_tools}，"
                f"将从反思阶段可用工具列表中排除，防止 LLM 绕过确认直接调用{Style.RESET_ALL}"
            )

        if self.tool_hub:
            all_tools = self.tool_hub.list_tools()
            reflect_available_tools = (
                [
                    t for t in all_tools
                    if t.name in agent.available_tools
                    and t.name not in user_rejected_tools  # NOTE: 排除被拒绝的工具
                ]
                if agent.available_tools
                else [
                    t for t in all_tools
                    if t.name not in user_rejected_tools  # NOTE: 排除被拒绝的工具
                ]
            )
        else:
            reflect_available_tools = []

        if user_rejected_tools and reflect_available_tools:
            logger.info(
                f"{Fore.GREEN}[Reflect Node] 过滤后反思阶段可用工具数量: {len(reflect_available_tools)}"
                f"（原总数: {len(self.tool_hub.list_tools()) if self.tool_hub else 0}，"
                f"排除了 {len(user_rejected_tools)} 个被拒绝工具）{Style.RESET_ALL}"
            )

        reflection_result = await self.reflection_engine.reflect(
            agent=agent,
            task=task,
            execution_result=execution_result_obj,
            error_context=current_error_ctx if current_error_ctx else None,
            available_tools=reflect_available_tools if reflect_available_tools else None,
            # NOTE: 传入 run_memory，优先使用 messages 格式传递历史执行记忆给反思引擎
            run_memory=state.get("run_memory"),
            iteration=iteration
        )
        
        logger.info(f"{Fore.GREEN}[Reflect Node] 反思完成{Style.RESET_ALL}")
        
        # 发送反思完成事件（含反思结果：是否成功、是否需要重规划、反馈建议）
        await send_agent_message(
            stream_callback=stream_callback,
            message_type="progress",
            content="反思完成",
            progress={"stage": "reflection_complete", "iteration": iteration},
            extra_data=reflection_result.to_dict()
        )
        
        # 更新状态
        state["iterations"] += 1
        state["messages"].append({
            "role": "system",
            "type": "reflection",
            "content": f"Reflection: success={reflection_result.success}, "
                      f"needs_replanning={reflection_result.needs_replanning}",
            "reflection": reflection_result.to_dict()
        })

        # NOTE: 将本轮反思结论追加到 reflection_history，供下一轮重规划时使用。
        # 写入 iteration（当前轮次编号）便于规划 Prompt 中按序展示历史。
        # 这是解决「repetitive planning」问题的关键写入点。
        reflection_entry = {
            **reflection_result.to_dict(),
            "iteration": iteration  # 记录是在哪一轮反思的（0-indexed）
        }
        current_history = state.get("reflection_history", []) or []
        current_history.append(reflection_entry)
        state["reflection_history"] = current_history
        logger.info(
            f"{Fore.CYAN}[Reflect Node] 已将第 {iteration} 轮反思结论写入历史，"
            f"当前共 {len(current_history)} 条记录{Style.RESET_ALL}"
        )

        # NOTE: 反思完成后，将结论写入 run_memory（以 assistant 消息格式记录）
        #       这样下一轮重规划时 LLM 在 messages 中能看到历史反思的判断
        run_memory: Optional[AgentRunMemory] = state.get("run_memory")
        if run_memory is not None:
            run_memory.write_reflection(
                iteration=iteration,
                result=reflection_result.to_dict()
            )
            # 同时打印记忆统计供调试观察
            stats = run_memory.get_stats()
            logger.info(
                f"{Fore.CYAN}[记忆统计] iteration={iteration} 反思写入完成, "
                f"记忆总条数={stats['total_messages']}, "
                f"条目类型={stats['entry_types']}{Style.RESET_ALL}"
            )

        # 将反思结果保存到 final_result (作为字典)
        if state["final_result"]:
            state["final_result"]["reflection"] = reflection_result.to_dict()
        
        return state
    
    async def _analyze_errors(
        self,
        agent,
        task: str,
        error_context: List[Dict[str, Any]],
        stream_callback=None,
        iteration: int = 0
    ) -> Dict[str, Any]:
        """
        使用 LLM 对本轮执行失败步骤进行根因分析，并通过流式事件推送给前端。

        本方法在每次执行节点发现失败步骤后被调用，收集结构化错误信息，
        构建 Prompt 让 LLM 进行根因分析，并将分析结果以 error_analysis 事件
        推送给前端展示。这样用户可以实时看到 Agent 如何理解自己的错误。

        Args:
            agent: 当前 Agent 实例（获取模型配置）
            task: 原始任务描述
            error_context: 本轮失败步骤的结构化错误列表
            stream_callback: 流式事件回调函数（可选）
            iteration: 当前迭代轮次

        Returns:
            Dict[str, Any]: LLM 分析结果，包含 root_cause / suggestions / corrective_plan
        """
        logger.info(
            f"{Fore.YELLOW}[错误分析] 开始调用 LLM 分析 {len(error_context)} 个错误{Style.RESET_ALL}"
        )

        # ── 格式化错误列表供 LLM 阅读 ────────────────────────────────
        error_lines = []
        for idx, err in enumerate(error_context, 1):
            step_desc = err.get("step_desc", "未知步骤")
            error_msg = err.get("error_msg", "")
            error_type = err.get("error_type", "")
            suggestion = err.get("suggestion", "")
            line = f"{idx}. [{error_type}] {step_desc}\n   错误信息: {error_msg}"
            if suggestion:
                line += f"\n   初步建议: {suggestion}"
            error_lines.append(line)

        error_text = "\n\n".join(error_lines)

        # ── 构建错误分析 Prompt ─────────────────────────────────────
        analysis_prompt = f"""你是 {agent.name}，{agent.description}

在执行以下任务的过程中遇到了一些错误：

任务：{task}

以下是本轮执行中发现的 {len(error_context)} 个失败步骤：

{error_text}

请对上述错误进行深度分析，以 JSON 格式返回：
{{
  "root_cause": "根本原因分析（一段话，解释为什么会发生这些错误，以及各错误之间的关联）",
  "suggestions": [
    "具体修复建议1",
    "具体修复建议2",
    "..."
  ],
  "corrective_plan": "修正计划（简要描述下一轮应该如何调整执行方案以避免同样的错误）"
}}

请只返回 JSON，不要包含其他文本。"""

        # ── 调用 LLM 进行错误分析 ───────────────────────────────────
        try:
            from app.llm_hub.inference import InferenceConfig
            import json as _json_parser

            config = InferenceConfig(
                model=agent.agent_config.execution_model,
                temperature=0.3,   # 低温度保证分析一致性
                max_tokens=1024,
                stream=False
            )

            logger.info(f"{Fore.YELLOW}[错误分析] 调用 LLM 分析错误根因...{Style.RESET_ALL}")
            response = await self.llm_hub.infer(
                messages=[{"role": "user", "content": analysis_prompt}],
                config=config
            )

            # ── 解析 LLM 返回的 JSON ─────────────────────────────────
            raw_content = response.content.strip()

            # 处理 markdown 代码块包裹的 JSON
            if "```json" in raw_content:
                start = raw_content.find("```json") + 7
                end = raw_content.find("```", start)
                raw_content = raw_content[start:end].strip()
            elif "```" in raw_content:
                start = raw_content.find("```") + 3
                end = raw_content.find("```", start)
                raw_content = raw_content[start:end].strip()

            analysis_result = _json_parser.loads(raw_content)
            logger.info(
                f"{Fore.GREEN}[错误分析] LLM 分析完成，"
                f"根因字数: {len(analysis_result.get('root_cause', ''))}{Style.RESET_ALL}"
            )

        except Exception as e:
            # LLM 调用或 JSON 解析失败时用规则兜底，不影响主流程
            logger.warning(
                f"{Fore.YELLOW}[错误分析] LLM 分析异常（{e}），使用规则兜底{Style.RESET_ALL}"
            )
            analysis_result = {
                "root_cause": f"自动分析失败（{str(e)}），请根据以下错误信息手动判断原因。",
                "suggestions": [
                    err.get("suggestion", "检查步骤参数是否正确")
                    for err in error_context
                ],
                "corrective_plan": "请根据错误详情调整执行计划，修正入参格式或选择替代工具。"
            }

        # ── 通过流式事件将分析结果推送给前端 ──────────────────────────
        event_data = {
            "errors": error_context,        # 原始失败步骤列表（供前端逐条展示）
            "root_cause": analysis_result.get("root_cause", ""),
            "suggestions": analysis_result.get("suggestions", []),
            "corrective_plan": analysis_result.get("corrective_plan", ""),
            "failed_count": len(error_context)
        }

        await send_agent_message(
            stream_callback=stream_callback,
            message_type="progress",
            content="错误分析完成",
            progress={"stage": "error_analysis", "iteration": iteration},
            extra_data=event_data
        )

        logger.info(
            f"{Fore.GREEN}[错误分析] error_analysis 事件已推送前端，"
            f"建议条数: {len(analysis_result.get('suggestions', []))}{Style.RESET_ALL}"
        )

        return analysis_result

    def _should_continue(self, state: AgentState) -> str:

        """
        条件边判断
        
        决定是继续迭代还是结束执行。
        
        判断逻辑（按优先级）：
        1. 达到最大迭代次数 → 强制结束
        2. 执行结果本身已成功（final_result.success=True）且无有效反思 → 直接结束
        3. 反思结果显示成功（reflection.success=True）→ 结束
        4. 反思结果要求重规划（reflection.needs_replanning=True）→ 继续
        5. 其他情况 → 默认结束
        
        Args:
            state: 当前状态
            
        Returns:
            str: "continue" 或 "end"
        """
        iterations = state["iterations"]
        final_result = state.get("final_result")
        
        logger.info(
            f"{Fore.CYAN}[Should Continue] 判断是否继续 - "
            f"迭代次数: {iterations}/{self.max_iterations}{Style.RESET_ALL}"
        )
        
        # ── 1. 检查是否达到最大迭代次数 ──
        if iterations >= self.max_iterations:
            logger.info(
                f"{Fore.YELLOW}[Should Continue] 已达最大迭代次数 {self.max_iterations}，强制结束{Style.RESET_ALL}"
            )
            return "end"
        
        # ── 2. 执行成功但没有有效反思结果 → 直接结束（避免因反思 LLM 失败而无限循环）──
        # NOTE: final_result 中的 success 字段来自 ExecutionResult.success
        #       当 execution 本已成功（有 final_answer），反思 LLM 调用失败只是锦上添花，
        #       不应该让整个任务因此无限重试。
        if final_result and final_result.get("success", False) and "reflection" not in final_result:
            logger.info(
                f"{Fore.GREEN}[Should Continue] 执行已成功且无有效反思结果，直接结束{Style.RESET_ALL}"
            )
            return "end"
        
        # ── 3. 检查是否有反思结果 ──
        if not final_result or "reflection" not in final_result:
            logger.warning(
                f"{Fore.YELLOW}[Should Continue] 没有执行结果或反思结果，结束执行{Style.RESET_ALL}"
            )
            return "end"
        
        reflection = final_result["reflection"]
        step_results = final_result.get("step_results", []) or []
        user_rejected_tools = state.get("user_rejected_tools", []) or []
        reflection_history = state.get("reflection_history", []) or []
        
        # ── 4. 反思结果显示任务成功 → 结束 ──
        if reflection.get("success", False):
            logger.info(
                f"{Fore.GREEN}[Should Continue] 反思判定任务成功完成，结束执行{Style.RESET_ALL}"
            )
            return "end"

        # ── 5.1 无可执行动作熔断：本轮仅输出 final_answer（或等价无动作）时结束 ──
        # 典型场景：用户拒绝关键工具后，后续计划已退化为“解释原因+给替代建议”，
        # 若继续迭代通常只会重复同样建议，属于无效循环。
        non_final_actions = [
            sr for sr in step_results
            if (sr.get("action") or "") != "final_answer"
        ]
        if user_rejected_tools and not non_final_actions:
            logger.warning(
                f"{Fore.YELLOW}[Should Continue] 检测到用户已拒绝关键工具且本轮无新可执行动作，"
                f"为避免无效循环，结束执行{Style.RESET_ALL}"
            )
            return "end"

        # ── 5.2 重复反思熔断：连续多轮反馈/总结高度重复时结束 ──
        # 设计目标：防止 LLM 持续返回 should_continue=true 导致循环。
        def _norm_text(v: Any) -> str:
            import re
            s = (v or "")
            s = str(s).strip().lower()
            # 去除数字与多余空白，降低“同义重复”中的表面差异
            s = re.sub(r"\d+(\.\d+)?", "", s)
            s = re.sub(r"\s+", " ", s)
            return s

        if len(reflection_history) >= 3:
            last3 = reflection_history[-3:]
            all_need_replan = all(
                (not h.get("success", False)) and bool(h.get("needs_replanning", False))
                for h in last3
            )
            # 取最近三轮 feedback+summary 归一化文本
            signatures = [
                (_norm_text(h.get("feedback")), _norm_text(h.get("summary")))
                for h in last3
            ]
            # 若最近三轮至少两轮签名相同，判定为重复反思循环
            repeated = len(set(signatures)) <= 2
            if all_need_replan and repeated:
                logger.warning(
                    f"{Fore.YELLOW}[Should Continue] 检测到连续重复反思（近3轮建议/总结高度相似），"
                    f"为避免循环，结束执行{Style.RESET_ALL}"
                )
                return "end"
        
        # ── 5.3 反思结果要求执行成功但标记需要重规划时，检查底层执行是否已成功 ──
        # HACK: 防止因反思 LLM 误判而无限重试已经成功执行的计划
        # todo 一会解开注释
        # if final_result.get("success", False) and reflection.get("needs_replanning", False):
        #     logger.warning(
        #         f"{Fore.YELLOW}[Should Continue] 执行已成功但反思要求重规划，"
        #         f"直接结束以避免无效重试{Style.RESET_ALL}"
        #     )
        #     return "end"

        # ── 6. LLM 自主判断是否继续（优先级较高）────
        # 如果 LLM 在反思时已经明确判断 should_continue，优先遵循 LLM 的判断
        if "should_continue" in reflection and reflection["should_continue"] is not None:
            if reflection["should_continue"]:
                logger.info(
                    f"{Fore.CYAN}[Should Continue] LLM 判断应该继续迭代，继续执行{Style.RESET_ALL}"
                )
                return "continue"
            else:
                logger.info(
                    f"{Fore.GREEN}[Should Continue] LLM 判断任务无法完成，结束执行{Style.RESET_ALL}"
                )
                return "end"

        # ── 7. 反思结果要求重规划 → 继续 ──
        if reflection.get("needs_replanning", False):
            logger.info(
                f"{Fore.CYAN}[Should Continue] 需要重新规划，继续迭代{Style.RESET_ALL}"
            )
            return "continue"

        # ── 8. 默认结束 ──
        logger.info(
            f"{Fore.YELLOW}[Should Continue] 默认结束执行{Style.RESET_ALL}"
        )
        return "end"
    
    async def execute(
        self,
        agent: Agent,
        task: str,
        conversation_id: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        user_rejected_tools: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        执行 Agent 任务
        
        Args:
            agent: Agent 实例
            task: 任务描述
            conversation_id: 会话 ID（可选）。若提供，则激活会话级记忆（Session Memory），
                             能将过往独立任务的执行摘要注入到本次任务的上下文中。
            conversation_history: 对话历史记录（通常来自于外部对话记录系统）
            user_rejected_tools: 用户已拒绝的工具列表（可选）
            
        Returns:
            Dict[str, Any]: 执行结果
        """
        logger.info(
            f"{Fore.BLUE}开始执行 Agent 任务 - Agent: {agent.name}{Style.RESET_ALL}"
        )
        logger.info(f"{Fore.CYAN}任务: {task}{Style.RESET_ALL}")
        
        try:
            # ── 提取会话级前置记忆（Session Memory） ──
            # 从全局的 AgentSessionMemory 获取当前会话以前的任务摘要，作为系统级历史记录前置发送。
            session_ctx_messages = []
            if conversation_id:
                session_mem = get_session_memory(conversation_id)
                session_ctx_messages = session_mem.build_context_messages()
                if session_ctx_messages:
                    logger.info(
                        f"{Fore.CYAN}[会话记忆] 成功获取会话 '{conversation_id}' 的 {len(session_ctx_messages)} 条历史任务摘要，"
                        f"将注入为本次任务的前置上下文{Style.RESET_ALL}"
                    )
                else:
                    logger.debug(f"{Fore.CYAN}[会话记忆] 会话 '{conversation_id}' 无历史任务摘要{Style.RESET_ALL}")

            # 初始化状态
            initial_state: AgentState = {
                "messages": session_ctx_messages + (conversation_history or []),
                "current_plan": None,
                "tool_outputs": [],
                "iterations": 0,
                "final_result": None,
                "task": task,
                "agent": agent,
                # NOTE: 初始为空列表，执行阶段会收集失败步骤信息并往这里写入
                "error_context": [],
                # NOTE: 初始为 None，LLM 对错误的根因分析结果会写入这里
                "error_analysis": None,
                # NOTE: 初始为空列表，每轮反思完成后会追加一条记录
                #       用于下一轮重规划时给 LLM 提供历史上下文
                "reflection_history": [],
                # NOTE: 初始为空字典，等待用户确认时写入 asyncio.Event
                "pending_confirmations": {},
                # NOTE: 初始为空字典，等待用户输入时写入 asyncio.Event
                "pending_user_inputs": {},
                # NOTE: 初始为空列表，用户拒绝某工具后记录匹名称
                "user_rejected_tools": [],
                # NOTE: 初始化 AgentRunMemory 实例，挂载本次任务运行记忆仓库。
                #       Plan/Execute/Reflect 三个节点均从此读写检索和德入新行为记录。
                "run_memory": AgentRunMemory(
                    task=task,
                    agent_id=agent.agent_id,
                    agent_name=agent.name,
                    context_messages=session_ctx_messages + (conversation_history or [])
                )
            }
            
            # NOTE: LangGraph 默认 recursion_limit=25，每次 plan→execute→reflect 算 3 步
            # 若 max_iterations=10，则需要至少 10×3=30 步，因此需要显式设置更大的限制。
            # 这里设置为 max_iterations*4+10，留有充足的余量。
            recursion_limit = self.max_iterations * 4 + 10
            logger.info(
                f"{Fore.BLUE}开始执行状态图，recursion_limit={recursion_limit}，"
                f"max_iterations={self.max_iterations}{Style.RESET_ALL}"
            )
            
            final_state = await self.graph.ainvoke(
                initial_state,
                config={"recursion_limit": recursion_limit}
            )
            
            logger.info(f"{Fore.GREEN}Agent 任务执行完成{Style.RESET_ALL}")
            logger.info(
                f"{Fore.GREEN}总迭代次数: {final_state['iterations']}{Style.RESET_ALL}"
            )
            
            # 序列化 messages 以供前端展示
            raw_messages = final_state.get("messages", [])
            serialized_messages = []
            for msg in raw_messages:
                if isinstance(msg, dict):
                    serialized_messages.append(msg)
                elif hasattr(msg, "model_dump"):
                    serialized_messages.append(msg.model_dump())
                elif hasattr(msg, "dict"):
                    serialized_messages.append(msg.dict())
                else:
                    role = getattr(msg, "type", "system")
                    content = getattr(msg, "content", str(msg))
                    serialized_messages.append({"role": role, "content": content})
            
            # ── 写入会话级记忆摘要 ──
            if conversation_id:
                try:
                    entry = extract_summary_from_run_memory(
                        run_memory=initial_state["run_memory"],
                        final_result=final_state.get("final_result", {}) or {}
                    )
                    get_session_memory(conversation_id).append_task_summary(entry)
                    logger.info(f"{Fore.GREEN}[会话记忆] 任务摘要已追加至会话 {conversation_id}{Style.RESET_ALL}")
                except Exception as e:
                    logger.error(f"{Fore.RED}[会话记忆] 提取/写入任务摘要失败: {e}{Style.RESET_ALL}")

            # 返回最终结果
            return {
                "success": True,
                "result": final_state.get("final_result"),
                "iterations": final_state["iterations"],
                "messages": serialized_messages
            }
            
        except Exception as e:
            logger.error(f"{Fore.RED}Agent 任务执行失败: {e}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": str(e),
                "iterations": 0
            }

    async def execute_with_callback(
        self,
        agent: Agent,
        task: str,
        stream_callback: Callable,
        conversation_id: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        user_rejected_tools: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        以流式回调模式执行 Agent 任务（供子 Agent 共享父级 SSE 流时调用）

        与 execute() 的区别：
          - 接收 stream_callback 参数并注入到 _build_graph()
          - 子 Agent 的规划/执行/反思事件（包括 user_confirm_required）会通过该回调
            推入父级的 SSE 流，前端可实时感知子 Agent 动态并弹出用户确认对话框

        注意：调用方在创建本执行器后应先将 _pending_confirmations 替换为父级的同名字典，
              以保证 confirm_id 在顶层 /agents/confirm 接口中可被正确查找。

        Args:
            agent: Agent 实例
            task: 任务描述
            stream_callback: 父级 SSE 流式回调（异步函数）
            conversation_id: 会话 ID（可选）。子 Agent 通常不需要自己查，这里支持预留以便极端复合情况。
            conversation_history: 对话历史（可选）
            user_rejected_tools: 用户已拒绝的工具列表（可选）

        Returns:
            Dict[str, Any]: 执行结果（格式同 execute()）
        """
        logger.info(
            f"{Fore.BLUE}[子Agent] execute_with_callback 开始 - Agent: {agent.name}{Style.RESET_ALL}"
        )
        logger.info(f"{Fore.CYAN}[子Agent] 任务: {task}{Style.RESET_ALL}")
        logger.info(
            f"{Fore.CYAN}[子Agent] stream_callback 已绑定，事件将推入父级 SSE 流{Style.RESET_ALL}"
        )

        try:
            session_ctx_messages = []
            if conversation_id:
                session_mem = get_session_memory(conversation_id)
                session_ctx_messages = session_mem.build_context_messages()

            # 构建带流式回调的状态图（与 execute_stream 共用同一图构建逻辑）
            graph = self._build_graph(stream_callback=stream_callback)

            initial_state: AgentState = {
                "messages": session_ctx_messages + (conversation_history or []),
                "current_plan": None,
                "tool_outputs": [],
                "iterations": 0,
                "final_result": None,
                "task": task,
                "agent": agent,
                "error_context": [],
                "error_analysis": None,
                "reflection_history": [],
                # NOTE: 调用方会在外部把本 executor._pending_confirmations 替换为父级字典，
                #       这里用 self._pending_confirmations 确保两者指向同一对象
                "pending_confirmations": self._pending_confirmations,
                # NOTE: 调用方会在外部把本 executor._pending_user_inputs 替换为父级字典，
                #       这里用 self._pending_user_inputs 确保两者指向同一对象
                "pending_user_inputs": self._pending_user_inputs,
                # ── 新增: 初始化时继承父级传来的被拒绝工具黑名单
                "user_rejected_tools": user_rejected_tools or [],
                # NOTE: 子 Agent 独立的 AgentRunMemory 实例，与父 Agent 相互独立。
                "run_memory": AgentRunMemory(
                    task=task,
                    agent_id=agent.agent_id,
                    agent_name=agent.name,
                    context_messages=session_ctx_messages + (conversation_history or [])
                )
            }

            recursion_limit = self.max_iterations * 4 + 10
            logger.info(
                f"{Fore.BLUE}[子Agent] 开始执行状态图，"
                f"recursion_limit={recursion_limit}，max_iterations={self.max_iterations}{Style.RESET_ALL}"
            )

            # 同步等待图执行完成（子 Agent 在父 execute_with_callback 的 await 中运行）
            final_state = await graph.ainvoke(
                initial_state,
                config={"recursion_limit": recursion_limit}
            )

            total_iterations = final_state.get("iterations", 0)
            final_result = final_state.get("final_result")

            logger.info(
                f"{Fore.GREEN}[子Agent] execute_with_callback 完成，"
                f"迭代次数={total_iterations}{Style.RESET_ALL}"
            )
            
            # ── 写入会话级记忆摘要 ──
            if conversation_id:
                try:
                    entry = extract_summary_from_run_memory(
                        run_memory=initial_state["run_memory"],
                        final_result=final_result or {}
                    )
                    get_session_memory(conversation_id).append_task_summary(entry)
                    logger.info(f"{Fore.GREEN}[会话记忆] 子Agent任务摘要已追加至会话 {conversation_id}{Style.RESET_ALL}")
                except Exception as e:
                    logger.error(f"{Fore.RED}[会话记忆] 提取/写入子Agent任务摘要失败: {e}{Style.RESET_ALL}")

            # NOTE: final_result 来自 ExecutionResult.to_dict()，其结构为：
            #   {"success": bool, "result": str, "step_results": list, "error": str|None, ...}
            #   注意：键名是 "success"（布尔值），而非 "status"（字符串），
            #   不能用 final_result.get("status") == "success" 判断，否则永远为 False。
            _exec_success = bool(final_result.get("success")) if final_result else False
            _exec_error   = final_result.get("error") if (final_result and not _exec_success) else None

            logger.info(
                f"{Fore.GREEN if _exec_success else Fore.YELLOW}"
                f"[子Agent] execute_with_callback 结果: success={_exec_success}, "
                f"result_len={len(str(final_result.get('result', ''))) if final_result else 0}字符"
                f"{Style.RESET_ALL}"
            )

            return {
                "success": _exec_success,
                "result":  final_result,
                "error":   _exec_error,
                # ── 子 Agent 运行结束后，将其最终的黑名单向上交差
                "user_rejected_tools": final_state.get("user_rejected_tools", []),
                # NOTE: 不返回 messages —— final_state["messages"] 包含 LangChain BaseMessage 对象，
                #       无法被 json.dumps() 序列化，且父 Agent 不需要子 Agent 的对话历史
                "iterations": total_iterations
            }

        except Exception as e:
            logger.error(
                f"{Fore.RED}[子Agent] execute_with_callback 失败: {e}{Style.RESET_ALL}"
            )
            # 通过 stream_callback 推送错误事件，让父级 SSE 流感知子 Agent 异常
            try:
                err_event = self._create_stream_event(
                    event_type="step_error",
                    error=f"子 Agent {agent.name} 执行失败: {str(e)}",
                    data={"agent_id": agent.agent_id, "agent_name": agent.name}
                )
                await stream_callback(err_event)
            except Exception:
                pass  # 推送错误事件失败不影响主流程

            return {
                "success": False,
                "error": str(e),
                "iterations": 0
            }

    async def execute_stream(
        self,
        agent: Agent,
        task: str,
        conversation_id: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        user_rejected_tools: Optional[List[str]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        流式执行 Agent 任务（使用 asyncio.Queue + 哨兵模式）
        
        这是一个异步生成器方法，逐步 yield 出 Agent 执行过程中的各个阶段事件，
        让前端可以实时展示 Agent 的思考、计划、工具调用等执行轨迹。
        
        核心设计：
        - 使用 asyncio.Queue 作为事件通道（与 event loop 同线程，无锁无竞争）
        - stream_callback 是异步函数，await queue.put() 将事件入队
        - 主生成器循环 await queue.get() 实时取出事件并 yield 给 SSE
        - 图执行完成后向队列放入 SENTINEL 哨兵值，通知主循环退出
        - 使用 asyncio.create_task 并发运行图执行与事件泵
        
        事件流向：
          plan_start → plan_complete
          step_start → tool_complete/skill_complete/delegate_complete → execute_complete
          reflection_start → reflection_complete
          final_answer → complete
        
        Args:
            agent: Agent 实例
            task: 任务描述
            conversation_id: 会话 ID（可选）。如果提供，会自动读取该会话历史任务的摘要作为初始上下文。
            conversation_history: 外部对话系统的多轮历史聊天记录（可选）
            user_rejected_tools: 用户拒绝过的工具黑名单列表（可选）
            
        Yields:
            Dict[str, Any]: 流式事件字典，字段：
                - event: 事件类型
                - iteration: 当前迭代次数
                - step_index: 当前步骤索引
                - step_total: 步骤总数
                - data: 事件数据
                - error: 错误信息
                - timestamp: 时间戳（毫秒）
        """
        logger.info(
            f"{Fore.BLUE}开始流式执行 Agent 任务 - Agent: {agent.name}{Style.RESET_ALL}"
        )
        logger.info(f"{Fore.CYAN}任务: {task[:200]}{Style.RESET_ALL}")

        # ─────────────────────────────────────────────────────────────────────
        # 1. 创建 asyncio.Queue 作为事件通道
        #    asyncio.Queue 是协程安全的，不需要 threading.Queue + to_thread
        # ─────────────────────────────────────────────────────────────────────
        event_queue: asyncio.Queue = asyncio.Queue()
        
        # 哨兵对象：放入队列表示图执行已完成，主循环应退出
        _SENTINEL = object()

        async def stream_callback(event: Dict[str, Any]):
            """
            异步流式回调：将事件放入 asyncio.Queue
            
            被 _plan_node / _execute_node / _reflect_node 中的
            await send_agent_message(...) 间接调用。
            由于是 async 函数，send_agent_message 内部会 await 它，
            从而保证事件在 yield 之前就被写入队列。
            """
            await event_queue.put(event)
            logger.debug(
                f"{Fore.BLUE}[流式回调] 事件已入队: "
                f"type={event.get('event')}, iter={event.get('iteration')}{Style.RESET_ALL}"
            )

        # ─────────────────────────────────────────────────────────────────────
        # 2. 构建带有流式回调的状态图（每次 execute_stream 创建独立图实例）
        # ─────────────────────────────────────────────────────────────────────
        try:
            # ── 提取会话级前置记忆（Session Memory） ──
            session_ctx_messages = []
            if conversation_id:
                session_mem = get_session_memory(conversation_id)
                session_ctx_messages = session_mem.build_context_messages()
                if session_ctx_messages:
                    logger.info(
                        f"{Fore.GREEN}[会话记忆] (流式) 会话 '{conversation_id}' 中读取到 "
                        f"{len(session_ctx_messages)} 条历史任务摘要，即将注入 AgentRunMemory{Style.RESET_ALL}"
                    )
                    # 逐条打印摘要内容摘要，方便确认注入内容是否正确
                    for idx, sm in enumerate(session_ctx_messages):
                        preview = str(sm.get("content", ""))[:100].replace("\n", " ")
                        logger.info(
                            f"{Fore.GREEN}[会话记忆] (流式) 摘要[{idx}]: {preview!r}{Style.RESET_ALL}"
                        )
                else:
                    logger.info(
                        f"{Fore.CYAN}[会话记忆] (流式) 会话 '{conversation_id}' 暂无历史任务摘要"
                        f"（这是该会话的第一次任务）{Style.RESET_ALL}"
                    )
        except Exception as e:
            logger.error(f"{Fore.RED}[会话记忆] 读取历史任务摘要失败: {e}{Style.RESET_ALL}")
            session_ctx_messages = []

        graph = self._build_graph(stream_callback=stream_callback)

        # 初始化 Agent 状态
        initial_state: AgentState = {
            "messages": session_ctx_messages + (conversation_history or []),
            "current_plan": None,
            "tool_outputs": [],
            "iterations": 0,
            "final_result": None,
            "task": task,
            "agent": agent,
            # NOTE: 初始为空列表，执行阶段会收集失败步骤信息并往这里写入
            "error_context": [],
            # NOTE: 初始为 None，LLM 对错误的根因分析结果会写入这里
            "error_analysis": None,
            # NOTE: 初始为空列表，每轮反思完成后会追加一条记录
            #       用于下一轮重规划时给 LLM 提供历史上下文
            "reflection_history": [],
            # NOTE: 初始为空字典，等待用户确认时写入 asyncio.Event
            "pending_confirmations": {},
            # NOTE: 初始为空字典，等待用户输入时写入 asyncio.Event
            "pending_user_inputs": {},
            # NOTE: 初始为空列表，用户拒绝某工具后记录其名称
            #       _reflect_node 会从 available_tools 中过滤这些工具，
            #       防止反思阶段 LLM 通过 tool_gateway 绕过用户确认再次执行被拒绝操作
            "user_rejected_tools": user_rejected_tools or [],
            # NOTE: 初始化 AgentRunMemory 实例，挂载本次流式任务运行记忆仓库。
            #       Plan/Execute/Reflect 三个节点均从此读写检索和写入新行为记录。
            #
            # ⚠️ 重要：必须传入 context_messages！
            #   这里包含了"会话摘要（session_ctx_messages）"和"对话历史（conversation_history）"。
            #   build_messages_for_planning() 和 build_messages_for_reflection() 会从
            #   self.context_messages 中读取这些前置上下文，注入到规划/反思 messages 的最前面。
            #   若不传，会话级记忆虽然被读取，但永远无法进入 LLM 的感知范围！
            "run_memory": AgentRunMemory(
                task=task,
                agent_id=agent.agent_id,
                agent_name=agent.name,
                context_messages=session_ctx_messages + (conversation_history or [])
                # 📌 解释：
                #   session_ctx_messages → 来自 AgentSessionMemory 的跨任务历史摘要
                #   conversation_history → 来自外部对话系统的多轮聊天记录（可选）
                #   两者合并后作为整次任务的「前置上下文背景」，优先于当前任务目标展示给 LLM
            )
        }

        # 递归深度：每次 plan→execute→reflect 循环约 3 步，留足余量
        recursion_limit = self.max_iterations * 4 + 10
        logger.info(
            f"{Fore.BLUE}开始执行状态图，recursion_limit={recursion_limit}，"
            f"max_iterations={self.max_iterations}{Style.RESET_ALL}"
        )

        # ─────────────────────────────────────────────────────────────────────
        # 3. 图执行后台任务：执行完毕后放入 SENTINEL 通知主循环
        # ─────────────────────────────────────────────────────────────────────
        final_state_holder: Dict[str, Any] = {}

        async def run_graph():
            """
            后台任务：运行 LangGraph 状态图
            - 图内节点通过 stream_callback 将事件放入队列
            - 执行完毕（或出错）后，放入 SENTINEL 通知主循环退出
            """
            try:
                logger.info(f"{Fore.BLUE}[后台任务] 图执行开始{Style.RESET_ALL}")
                result = await graph.ainvoke(
                    initial_state,
                    config={"recursion_limit": recursion_limit}
                )
                final_state_holder["result"] = result
                logger.info(
                    f"{Fore.GREEN}[后台任务] 图执行完成，"
                    f"迭代次数: {result.get('iterations', 0)}{Style.RESET_ALL}"
                )
            except Exception as e:
                final_state_holder["error"] = str(e)
                logger.error(
                    f"{Fore.RED}[后台任务] 图执行异常: {e}{Style.RESET_ALL}"
                )
            finally:
                # 无论成功还是失败，都放入 SENTINEL 让主循环退出
                await event_queue.put(_SENTINEL)
                logger.debug(f"{Fore.YELLOW}[后台任务] SENTINEL 已入队{Style.RESET_ALL}")

        # ─────────────────────────────────────────────────────────────────────
        # 4. 启动后台图执行任务，主循环实时读取并 yield 事件
        # ─────────────────────────────────────────────────────────────────────
        graph_task = asyncio.create_task(run_graph())
        
        try:
            # 主循环：持续从队列取事件并 yield 给 SSE 连接
            # 遇到 SENTINEL 时退出循环
            event_count = 0
            while True:
                # await queue.get() 会让出控制权给 event loop，
                # 使 run_graph() 中的图节点得以执行和产生事件
                raw_event = await event_queue.get()
                
                # 收到哨兵，说明图执行已完成
                if raw_event is _SENTINEL:
                    logger.debug(
                        f"{Fore.YELLOW}[主循环] 收到 SENTINEL，"
                        f"共处理 {event_count} 个事件{Style.RESET_ALL}"
                    )
                    break
                
                # yield 真实事件给 SSE 连接
                event_count += 1
                logger.debug(
                    f"{Fore.CYAN}[主循环] yield 事件 #{event_count}: "
                    f"{raw_event.get('event')}{Style.RESET_ALL}"
                )
                yield raw_event
            
            # ── 等待图任务完全结束（此时应已完成）────────────────────────────
            await graph_task
            
        except Exception as e:
            # 主循环异常：取消图任务，发送错误事件
            logger.error(f"{Fore.RED}[主循环] 事件读取异常: {e}{Style.RESET_ALL}")
            graph_task.cancel()
            try:
                await graph_task
            except asyncio.CancelledError:
                pass
            
            yield self._create_stream_event(
                event_type="error",
                error=f"流式执行内部错误: {str(e)}"
            )
            yield self._create_stream_event(
                event_type="complete",
                data={"success": False, "error": str(e)}
            )
            return

        # ─────────────────────────────────────────────────────────────────────
        # 5. 图执行完成后，发送最终答案和完成事件
        # ─────────────────────────────────────────────────────────────────────
        
        # 检查是否有错误
        if "error" in final_state_holder:
            error_msg = final_state_holder["error"]
            logger.error(f"{Fore.RED}[流式执行] 图执行失败: {error_msg}{Style.RESET_ALL}")
            yield self._create_stream_event(
                event_type="error",
                error=error_msg
            )
            yield self._create_stream_event(
                event_type="complete",
                data={"success": False, "error": error_msg}
            )
            return
        
        # 获取最终状态和结果
        final_state = final_state_holder.get("result", {})
        final_result = final_state.get("final_result")
        total_iterations = final_state.get("iterations", 0)
        
        logger.info(
            f"{Fore.GREEN}[流式执行] 准备发送最终答案, "
            f"迭代次数={total_iterations}, "
            f"has_result={final_result is not None}{Style.RESET_ALL}"
        )
        
        if final_result:
            # 提取执行结果和反思数据
            result_data = final_result.get("result")
            reflection_data = final_result.get("reflection")
            
            logger.info(
                f"{Fore.GREEN}[流式执行] 发送 final_answer 事件, "
                f"result_type={type(result_data).__name__}{Style.RESET_ALL}"
            )
            
            # 发送最终答案事件（包含完整结果和反思）
            yield self._create_stream_event(
                event_type="final_answer",
                iteration=total_iterations,
                data={
                    "result": result_data,
                    "reflection": reflection_data
                }
            )
        else:
            logger.warning(
                f"{Fore.YELLOW}[流式执行] 没有最终结果（final_result=None）{Style.RESET_ALL}"
            )
        
        # 发送执行完成事件（表示整个流式会话结束）
        success_flag = final_result.get("success", False) if final_result else False
        
        # ── 写入会话级记忆摘要 ──
        if conversation_id:
            try:
                # 获取存在 result 里的 final_state 来获取 run_memory
                state_snapshot = final_state_holder.get("result", {})
                run_memory_obj = state_snapshot.get("run_memory") or initial_state["run_memory"]
                entry = extract_summary_from_run_memory(
                    run_memory=run_memory_obj,
                    final_result=final_result or {}
                )
                get_session_memory(conversation_id).append_task_summary(entry)
                logger.info(f"{Fore.GREEN}[会话记忆] 流式任务摘要已追加至会话 {conversation_id}{Style.RESET_ALL}")
            except Exception as e:
                logger.error(f"{Fore.RED}[会话记忆] 提取/写入流式任务摘要失败: {e}{Style.RESET_ALL}")
                
        yield self._create_stream_event(
            event_type="complete",
            iteration=total_iterations,
            data={
                "success": success_flag,
                "iterations": total_iterations
            }
        )
        
        logger.info(f"{Fore.GREEN}Agent 流式执行完成{Style.RESET_ALL}")
        logger.info(f"{Fore.GREEN}总迭代次数: {total_iterations}{Style.RESET_ALL}")


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}LangGraph Agent Executor 测试{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
    
    # 测试需要异步环境
    print(f"{Fore.YELLOW}请使用 pytest 运行测试{Style.RESET_ALL}")
    
    print(f"\n{Fore.GREEN}模块加载成功!{Style.RESET_ALL}\n")
