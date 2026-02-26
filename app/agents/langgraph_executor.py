"""
LangGraph Agent Executor (基于 LangGraph 的 Agent 执行器)
================================

本模块使用 LangGraph 框架实现 Agent 的状态管理和执行流程。

功能特点：
1. 使用 StateGraph 管理 Agent 状态
2. 实现 Plan -> Execute -> Reflect 循环
3. 支持条件边和状态转换
4. 集成现有的 Planning、Execution、Reflection 引擎

作者: AI Agent Team
创建时间: 2026-02-15
"""

from typing import TypedDict, Dict, List, Any, Optional, Annotated
from typing_extensions import TypedDict as TypedDictExt
from loguru import logger
from colorama import Fore, Style

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from app.agents.base import Agent
from app.agents.planning import PlanningEngine, Plan
from app.agents.execution import ExecutionEngine, ExecutionResult
from app.agents.reflection import ReflectionEngine


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


class LangGraphAgentExecutor:
    """
    基于 LangGraph 的 Agent 执行器
    
    使用 StateGraph 管理 Agent 的执行生命周期
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
    
    def _build_graph(self) -> StateGraph:
        """
        构建 LangGraph 状态图
        
        定义节点、边和条件边
        
        Returns:
            StateGraph: 编译后的状态图
        """
        logger.info(f"{Fore.BLUE}构建 LangGraph 状态图{Style.RESET_ALL}")
        
        # 创建状态图
        workflow = StateGraph(AgentState)
        
        # 添加节点
        workflow.add_node("plan", self._plan_node)
        workflow.add_node("execute", self._execute_node)
        workflow.add_node("reflect", self._reflect_node)
        
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
    
    async def _plan_node(self, state: AgentState) -> AgentState:
        """
        规划节点
        
        调用 PlanningEngine 创建执行计划
        
        Args:
            state: 当前状态
            
        Returns:
            AgentState: 更新后的状态
        """
        logger.info(f"{Fore.BLUE}[Plan Node] 开始规划{Style.RESET_ALL}")
        
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
        
        # 更新状态
        state["current_plan"] = plan
        state["messages"].append({
            "role": "system",
            "content": f"Created plan with {len(plan.steps)} steps"
        })
        
        return state
    
    async def _execute_node(self, state: AgentState) -> AgentState:
        """
        执行节点
        
        调用 ExecutionEngine 执行计划
        
        Args:
            state: 当前状态
            
        Returns:
            AgentState: 更新后的状态
        """
        logger.info(f"{Fore.BLUE}[Execute Node] 开始执行计划{Style.RESET_ALL}")
        
        agent = state["agent"]
        plan = state["current_plan"]
        
        # 执行计划（把 task 放入 context，供 _synthesize_answer 使用）
        execution_result = await self.execution_engine.execute_plan(
            agent=agent,
            plan=plan,
            context={"task": state.get("task", "")}
        )
        
        logger.info(f"{Fore.GREEN}[Execute Node] 计划执行完成{Style.RESET_ALL}")
        
        # 更新状态
        state["tool_outputs"].extend(execution_result.step_results)
        state["messages"].append({
            "role": "system",
            "content": f"Executed plan: success={execution_result.success}"
        })
        
        # 如果执行成功，保存结果
        if execution_result.success:
            state["final_result"] = execution_result.to_dict()
        
        return state
    
    async def _reflect_node(self, state: AgentState) -> AgentState:
        """
        反思节点
        
        调用 ReflectionEngine 评估执行结果
        
        Args:
            state: 当前状态
            
        Returns:
            AgentState: 更新后的状态
        """
        logger.info(f"{Fore.BLUE}[Reflect Node] 开始反思{Style.RESET_ALL}")
        
        agent = state["agent"]
        task = state["task"]
        final_result = state.get("final_result")
        
        if not final_result:
            logger.warning(f"{Fore.YELLOW}[Reflect Node] 没有执行结果，跳过反思{Style.RESET_ALL}")
            state["messages"].append({
                "role": "system",
                "content": "No execution result to reflect on"
            })
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
        
        # 更新状态
        state["iterations"] += 1
        state["messages"].append({
            "role": "system",
            "content": f"Reflection: success={reflection_result.success}, "
                      f"needs_replanning={reflection_result.needs_replanning}"
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
