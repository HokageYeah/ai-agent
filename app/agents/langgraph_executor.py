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
import asyncio


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
        max_iterations: int = 10,
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
        创建流式事件数据
        
        Args:
            event_type: 事件类型
            iteration: 当前迭代次数
            step_index: 当前步骤索引
            step_total: 步骤总数
            data: 事件数据
            error: 错误信息
            
        Returns:
            Dict[str, Any]: 事件数据字典
        """
        event = {
            "event": event_type,
            "iteration": iteration,
            "timestamp": time.time() * 1000,  # 毫秒时间戳
        }
        
        if step_index is not None:
            event["step_index"] = step_index
        if step_total is not None:
            event["step_total"] = step_total
        if data is not None:
            event["data"] = data
        if error is not None:
            event["error"] = error
            
        return event
    
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
        
        # 发送开始规划事件（await 必须加，否则 async 方法不执行）
        await self._emit_stream_event(
            stream_callback,
            event_type="plan_start",
            iteration=iteration,
            data={"message": "Agent 正在分析任务并制定执行计划..."}
        )
        
        agent = state["agent"]
        task = state["task"]
        
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
        
        # 创建计划
        plan = await self.planning_engine.create_plan(
            agent=agent,
            task=task,
            available_tools=available_tools,
            available_skills=available_skills
        )
        
        logger.info(f"{Fore.GREEN}[Plan Node] 计划创建完成{Style.RESET_ALL}")
        
        # 发送规划完成事件（含推理过程和步骤列表）
        await self._emit_stream_event(
            stream_callback,
            event_type="plan_complete",
            iteration=iteration,
            data={
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
        await self._emit_stream_event(
            stream_callback,
            event_type="step_start",
            iteration=iteration,
            step_index=0,
            step_total=step_total,
            data={"message": f"开始执行 {step_total} 个计划步骤..."}
        )
        
        # 执行计划（把 task 放入 context，供 _synthesize_answer 使用）
        execution_result = await self.execution_engine.execute_plan(
            agent=agent,
            plan=plan,
            context={"task": state.get("task", "")}
        )
        
        logger.info(f"{Fore.GREEN}[Execute Node] 计划执行完成{Style.RESET_ALL}")
        
        # 遍历步骤结果，逐个发送流式事件（每个步骤对应前端一个时间轴节点）
        if execution_result.step_results:
            for idx, step_result in enumerate(execution_result.step_results, 1):
                action = step_result.get("action", "unknown")
                
                logger.debug(
                    f"{Fore.CYAN}[Execute Node] 发送步骤事件 {idx}/{step_total}: "
                    f"action={action}{Style.RESET_ALL}"
                )
                
                # 根据步骤类型发送对应事件（await 必须加）
                if action == "tool":
                    # 工具调用完成事件
                    await self._emit_stream_event(
                        stream_callback,
                        event_type="tool_complete",
                        iteration=iteration,
                        step_index=idx,
                        step_total=step_total,
                        data=step_result
                    )
                elif action == "delegate":
                    # 子 Agent 委派完成事件
                    await self._emit_stream_event(
                        stream_callback,
                        event_type="delegate_complete",
                        iteration=iteration,
                        step_index=idx,
                        step_total=step_total,
                        data=step_result
                    )
                elif action == "skill":
                    # 技能调用完成事件（使用专用 skill_complete 事件类型）
                    await self._emit_stream_event(
                        stream_callback,
                        event_type="skill_complete",
                        iteration=iteration,
                        step_index=idx,
                        step_total=step_total,
                        data=step_result
                    )
                else:
                    # 其他步骤（如 final_answer 合成），添加步骤名称描述
                    step_action = step_result.get("action", "unknown")
                    step_name = ""
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
                    
                    await self._emit_stream_event(
                        stream_callback,
                        event_type="step_complete",
                        iteration=iteration,
                        step_index=idx,
                        step_total=step_total,
                        data={
                            **step_result,
                            "step_name": step_name,
                            "message": f"步骤 {idx}/{step_total} 完成: {step_name}"
                        }
                    )
                
                # 若步骤失败，额外发送错误事件
                if not step_result.get("success", True):
                    await self._emit_stream_event(
                        stream_callback,
                        event_type="step_error",
                        iteration=iteration,
                        step_index=idx,
                        step_total=step_total,
                        error=step_result.get("error", "Unknown error"),
                        data=step_result
                    )
        
        # 更新状态
        state["tool_outputs"].extend(execution_result.step_results)
        state["messages"].append({
            "role": "system",
            "type": "execution",
            "content": f"Executed plan: success={execution_result.success}",
            "step_results": execution_result.step_results
        })
        
        # 如果执行成功，保存结果
        if execution_result.success:
            state["final_result"] = execution_result.to_dict()
        
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
        
        await self._emit_stream_event(
            stream_callback,
            event_type="execute_complete",
            iteration=iteration,
            step_index=step_total,
            step_total=step_total,
            data={
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
        await self._emit_stream_event(
            stream_callback,
            event_type="reflection_start",
            iteration=iteration,
            data={"message": "Agent 正在评估执行结果..."}
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
            await self._emit_stream_event(
                stream_callback,
                event_type="reflection_complete",
                iteration=iteration,
                data={"skipped": True, "message": "无执行结果，跳过反思"}
            )
            return state
        
        # 将字典转换为 ExecutionResult 对象
        # 注意：需要过滤掉可能存在的额外字段（如之前的 reflection）
        execution_result_args = {
            k: v for k, v in final_result.items() 
            if k in ["success", "result", "step_results", "error"]
        }
        execution_result_obj = ExecutionResult(**execution_result_args)
        
        # 反思执行结果
        reflection_result = await self.reflection_engine.reflect(
            agent=agent,
            task=task,
            execution_result=execution_result_obj
        )
        
        logger.info(f"{Fore.GREEN}[Reflect Node] 反思完成{Style.RESET_ALL}")
        
        # 发送反思完成事件（含反思结果：是否成功、是否需要重规划、反馈建议）
        await self._emit_stream_event(
            stream_callback,
            event_type="reflection_complete",
            iteration=iteration,
            data=reflection_result.to_dict()
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
        
        # 将反思结果保存到 final_result (作为字典)
        if state["final_result"]:
            state["final_result"]["reflection"] = reflection_result.to_dict()
        
        return state
    
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
        
        # ── 4. 反思结果显示任务成功 → 结束 ──
        if reflection.get("success", False):
            logger.info(
                f"{Fore.GREEN}[Should Continue] 反思判定任务成功完成，结束执行{Style.RESET_ALL}"
            )
            return "end"
        
        # ── 5. 反思结果要求执行成功但标记需要重规划时，检查底层执行是否已成功 ──
        # HACK: 防止因反思 LLM 误判而无限重试已经成功执行的计划
        if final_result.get("success", False) and reflection.get("needs_replanning", False):
            logger.warning(
                f"{Fore.YELLOW}[Should Continue] 执行已成功但反思要求重规划，"
                f"直接结束以避免无效重试{Style.RESET_ALL}"
            )
            return "end"
        
        # ── 6. 反思结果要求重规划 → 继续 ──
        if reflection.get("needs_replanning", False):
            logger.info(
                f"{Fore.CYAN}[Should Continue] 需要重新规划，继续迭代{Style.RESET_ALL}"
            )
            return "continue"
        
        # ── 7. 默认结束 ──
        logger.info(
            f"{Fore.YELLOW}[Should Continue] 默认结束执行{Style.RESET_ALL}"
        )
        return "end"
    
    async def execute(
        self,
        agent: Agent,
        task: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        执行 Agent 任务
        
        Args:
            agent: Agent 实例
            task: 任务描述
            conversation_history: 对话历史（可选）
            
        Returns:
            Dict[str, Any]: 执行结果
        """
        logger.info(
            f"{Fore.BLUE}开始执行 Agent 任务 - Agent: {agent.name}{Style.RESET_ALL}"
        )
        logger.info(f"{Fore.CYAN}任务: {task}{Style.RESET_ALL}")
        
        try:
            # 初始化状态
            initial_state: AgentState = {
                "messages": conversation_history or [],
                "current_plan": None,
                "tool_outputs": [],
                "iterations": 0,
                "final_result": None,
                "task": task,
                "agent": agent
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

    async def execute_stream(
        self,
        agent: Agent,
        task: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None
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
            conversation_history: 对话历史（可选）
            
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
            await self._emit_stream_event(...) 间接调用。
            由于是 async 函数，_emit_stream_event 内部会 await 它，
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
        graph = self._build_graph(stream_callback=stream_callback)

        # 初始化 Agent 状态
        initial_state: AgentState = {
            "messages": conversation_history or [],
            "current_plan": None,
            "tool_outputs": [],
            "iterations": 0,
            "final_result": None,
            "task": task,
            "agent": agent
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
