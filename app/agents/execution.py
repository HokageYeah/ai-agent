"""
执行引擎 (Execution Engine)
================================

本模块负责执行由 Planning Engine 生成的计划。

功能特点：
1. 逐步执行计划中的每个步骤
2. 支持工具调用、技能调用、子 Agent 委派
3. 实现错误处理和恢复机制
4. 收集执行结果

作者: AI Agent Team
创建时间: 2026-02-15
"""

import re
import json as _json
from typing import Dict, List, Any, Optional
from typing import Dict as DictType
from typing import List as ListType
from loguru import logger
from colorama import Fore, Style

from app.agents.base import Agent
from app.agents.planning import Plan, PlanStep
from app.tools.hub import ToolHub
from app.skills.manager import SkillManager


class ExecutionResult:
    """执行结果"""
    
    def __init__(
        self,
        success: bool,
        result: Any,
        step_results: List[Dict[str, Any]] = None,
        error: Optional[str] = None
    ):
        """
        初始化执行结果
        
        Args:
            success: 是否成功
            result: 最终结果
            step_results: 每个步骤的执行结果
            error: 错误信息
        """
        self.success = success
        self.result = result
        self.step_results = step_results or []
        self.error = error
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "result": self.result,
            "step_results": self.step_results,
            "error": self.error
        }


class ExecutionEngine:
    """
    执行引擎
    
    执行由 Planning Engine 生成的计划
    """
    
    def __init__(
        self,
        tool_hub: ToolHub,
        skill_manager: SkillManager,
        llm_hub,
        child_agent_manager=None,
        tool_gateway=None
    ):
        """
        初始化执行引擎
        
        Args:
            tool_hub: 工具中心
            skill_manager: 技能管理器
            llm_hub: LLM Hub 实例
            child_agent_manager: 子 Agent 管理器（可选）
            tool_gateway: ToolCallingGateway 实例（可选）
                         当提供时，_execute_tool() 会优先通过网关执行工具调用，
                         统一享受网关的参数校验、日志统计、超时控制等能力；
                         未提供时降级为直接调用 ToolHub 中的工具实例。
        """
        self.tool_hub = tool_hub
        self.skill_manager = skill_manager
        self.llm_hub = llm_hub
        self.child_agent_manager = child_agent_manager
        # ToolCallingGateway 实例：路由所有工具调用，实现统一管控
        self.tool_gateway = tool_gateway
        
        if tool_gateway:
            logger.info(
                f"{Fore.GREEN}执行引擎初始化完成 "
                f"[工具网关: 已启用]{Style.RESET_ALL}"
            )
        else:
            logger.info(
                f"{Fore.GREEN}执行引擎初始化完成 "
                f"[工具网关: 未配置，使用直接调用模式]{Style.RESET_ALL}"
            )
    
    async def execute_plan(
        self,
        agent: Agent,
        plan: Plan,
        context: Optional[Dict[str, Any]] = None
    ) -> ExecutionResult:
        """
        执行计划
        
        Args:
            agent: Agent 实例
            plan: 执行计划
            context: 执行上下文
            
        Returns:
            ExecutionResult: 执行结果
        """
        logger.info(
            f"{Fore.BLUE}开始执行计划，共 {len(plan.steps)} 个步骤{Style.RESET_ALL}"
        )
        
        step_results = []
        final_result = None
        
        try:
            for i, step in enumerate(plan.steps, 1):
                logger.info(
                    f"{Fore.CYAN}执行步骤 {i}/{len(plan.steps)}: "
                    f"action={step.action}{Style.RESET_ALL}"
                )
                
                # ═══════════════════════════════════════════════════════════════
                # 【步骤参数占位符替换】
                # LLM 规划时可能使用占位符如 {{first_search_result_url}}，
                # 需要根据已执行步骤的结果动态替换为真实数据
                # ═══════════════════════════════════════════════════════════════
                step = self._resolve_step_placeholders(step, step_results)
                
                # 执行步骤（把已完成步骤结果传入，供 skill 等使用）
                step_result = await self._execute_step(agent, step, context, step_results)
                step_results.append(step_result)
                
                # 如果是 final_answer，先合成再返回
                if step.action == "final_answer":
                    template = step.params.get("content", "")
                    
                    # 收集本轮所有成功的工具/技能/委派结果（排除 final_answer 步骤本身）
                    tool_results = [
                        r for r in step_results
                        if r.get("success") and r.get("result")
                        and r.get("action") != "final_answer"
                    ]
                    
                    # 只要有真实数据（工具/技能/委派结果），就调用 LLM 合成最终答案。
                    # LLM 在规划阶段还没有执行结果，final_answer.content 只是意图描述
                    # 或占位符模板，不能直接返回给用户。
                    should_synthesize = bool(tool_results)
                    
                    if should_synthesize:
                        logger.info(
                            f"{Fore.BLUE}[执行引擎] 存在工具/委派执行结果，"
                            f"调用 LLM 合成真实答案...{Style.RESET_ALL}"
                        )
                        final_result = await self._synthesize_answer(
                            agent=agent,
                            task=context.get("task", "") if context else "",
                            tool_results=tool_results,
                            template=template
                        )
                    elif template:
                        final_result = template
                    elif tool_results:
                        # 没有 LLM 合成条件，直接拼接工具结果
                        parts = []
                        for r in tool_results:
                            label = r.get("tool_name") or r.get("agent_id") or r.get("action", "")
                            val = r["result"]
                            if isinstance(val, dict):
                                val = _json.dumps(val, ensure_ascii=False, indent=2)
                            parts.append(f"【{label}】\n{val}")
                        final_result = "\n\n".join(parts)
                    else:
                        final_result = "执行完成，但没有产生具体结果。"

                    logger.info(
                        f"{Fore.GREEN}执行完成，获得最终答案{Style.RESET_ALL}"
                    )
                    break
                
                # 检查步骤是否成功
                if not step_result.get("success", True):
                    logger.warning(
                        f"{Fore.YELLOW}步骤 {i} 执行失败: "
                        f"{step_result.get('error', 'Unknown error')}{Style.RESET_ALL}"
                    )
                    # 继续执行后续步骤（也可以选择中断）
            
            # 如果没有 final_answer，使用最后一个步骤的结果
            if final_result is None and step_results:
                final_result = step_results[-1].get("result", "")
            
            logger.info(f"{Fore.GREEN}计划执行成功{Style.RESET_ALL}")
            
            return ExecutionResult(
                success=True,
                result=final_result,
                step_results=step_results
            )
            
        except Exception as e:
            logger.error(f"{Fore.RED}执行计划时发生错误: {e}{Style.RESET_ALL}")
            
            return ExecutionResult(
                success=False,
                result=None,
                step_results=step_results,
                error=str(e)
            )
    
    async def _synthesize_answer(
        self,
        agent: Agent,
        task: str,
        tool_results: List[Dict[str, Any]],
        template: str = ""
    ) -> str:
        """
        调用 LLM 将工具/技能返回的原始数据合成为自然语言的最终答案。

        在 final_answer 的 content 包含占位符（如 [status]、[customer_name]）
        或为空时触发，避免把模板字符串作为最终结果返回给用户。

        Args:
            agent: 当前执行的 Agent 实例（用于取角色名）
            task: 原始用户任务描述
            tool_results: 本轮所有成功的工具/技能/委派结果列表
            template: LLM 规划时写的 final_answer 模板（可能含占位符）

        Returns:
            str: 基于真实数据合成的自然语言答案
        """
        # ── 格式化工具结果，供 LLM 阅读 ──────────────────────
        result_parts = []
        for idx, r in enumerate(tool_results, 1):
            label = r.get("tool_name") or r.get("agent_id") or r.get("action", f"步骤{idx}")
            # 对 delegate 结果保留子 Agent 的详细执行轨迹，避免上层合成时丢失关键信息
            # （如子 Agent 内 file_write 的真实写入结果）
            if r.get("action") == "delegate":
                val = {
                    "agent_id": r.get("agent_id"),
                    "success": r.get("success"),
                    "result": r.get("result"),
                    "step_results": r.get("step_results", []),
                    "error": r.get("error"),
                }
            else:
                val = r.get("result", "")
            if isinstance(val, dict):
                val_str = _json.dumps(val, ensure_ascii=False, indent=2)
            else:
                val_str = str(val)
            # 截断超长输出，防止 token 超限
            if len(val_str) > 3000:
                val_str = val_str[:3000] + "\n...（内容已截断）"
            result_parts.append(f"[来源: {label}]\n{val_str}")

        results_text = "\n\n".join(result_parts)

        synthesis_prompt = f"""你是 {agent.name}，{agent.description}

用户任务：{task}

以下是执行过程中获取到的数据：

{results_text}

请根据以上数据，用清晰、友好的自然语言回答用户的任务需求。
要求：
1. 直接给出具体数据，不要使用 [xxx] 这样的占位符
2. 信息完整，涵盖用户关心的所有字段
3. 格式清晰，必要时使用列表或分段展示
4. 如果数据中有错误或空值，如实告知
5. 如果任务包含“写入本地文件/保存到文件”，必须优先说明是否写入成功、写入路径与写入内容来源，禁止只返回查询结果。

请直接输出最终回答，不要包含任何前缀说明。"""

        try:
            from app.llm_hub.inference import InferenceConfig
            
            # 获取工具定义（用于 LLM function calling）
            tools = []
            if self.tool_hub:
                tools = self.tool_hub.get_schemas()
                logger.debug(f"{Fore.CYAN}[执行引擎] 答案合成 - 已注册 {len(tools)} 个工具定义{Style.RESET_ALL}")
            
            config = InferenceConfig(
                model=agent.agent_config.execution_model,
                stream=False,
                temperature=0.3,   # 答案合成用低温度，减少幻觉
                tools=tools
            )
            response = await self.llm_hub.infer(
                messages=[{"role": "user", "content": synthesis_prompt}],
                config=config
            )
            answer = response.content.strip()
            logger.info(
                f"{Fore.GREEN}[执行引擎] LLM 答案合成完成，"
                f"长度: {len(answer)} 字符{Style.RESET_ALL}"
            )
            return answer

        except Exception as e:
            logger.error(
                f"{Fore.RED}[执行引擎] LLM 答案合成失败，回退到原始数据拼接: {e}{Style.RESET_ALL}"
            )
            # 合成失败时降级：把原始工具结果直接拼接返回
            return "\n\n".join(
                f"【{r.get('tool_name') or r.get('action', '')}】\n"
                + (_json.dumps(r["result"], ensure_ascii=False, indent=2)
                   if isinstance(r["result"], dict) else str(r["result"]))
                for r in tool_results
                if r.get("result")
            ) or template or "执行完成，但未能生成最终答案。"

    def _resolve_step_placeholders(
        self,
        step: PlanStep,
        prev_results: List[Dict[str, Any]]
    ) -> PlanStep:
        """
        解析并替换步骤参数中的占位符
        
        LLM 在规划阶段可能使用占位符（如 {{first_search_result_url}}）来引用前序步骤的结果。
        本方法在执行前将这些占位符替换为真实数据。
        
        支持的占位符格式：
        - {{first_search_result_url}} - 第一个搜索结果的 URL
        - {{first_search_result_title}} - 第一个搜索结果的标题
        - {{first_search_result}} - 第一个搜索结果的完整信息
        - {{last_tool_result}} - 最后一个工具的执行结果
        - {{last_tool_result_url}} - 最后一个工具结果中的 URL（如果存在）
        
        Args:
            step: 当前执行的计划步骤
            prev_results: 已完成步骤的结果列表
            
        Returns:
            PlanStep: 替换占位符后的步骤（副本）
        """
        import re
        import copy
        
        # 创建步骤的深拷贝，避免修改原始计划
        resolved_step = copy.deepcopy(step)
        
        # 获取前序步骤中有用的数据
        search_result_url = None
        search_result_title = None
        search_result_snippet = None
        last_tool_result = None
        
        for result in prev_results:
            if not result.get("success"):
                continue
            
            # 提取搜索结果信息
            if result.get("action") == "tool" and result.get("tool_name") == "search":
                tool_result = result.get("result", {})
                if isinstance(tool_result, dict):
                    results_list = tool_result.get("results", [])
                    if results_list:
                        first_result = results_list[0]
                        search_result_url = first_result.get("url")
                        search_result_title = first_result.get("title")
                        search_result_snippet = first_result.get("snippet")
            
            # 记录最后一个工具结果
            if result.get("action") == "tool":
                last_tool_result = result.get("result")
        
        # 如果没有搜索结果，检查是否可以从任何工具结果中提取 URL
        if not search_result_url and last_tool_result:
            if isinstance(last_tool_result, dict):
                search_result_url = last_tool_result.get("url") or last_tool_result.get("first_url")
        
        # 定义替换映射（支持两种格式：{{...}} 和 {...}）
        replacements = [
            # 格式一：双花括号 {{...}}
            ("{{first_search_result_url}}", search_result_url or ""),
            ("{{first_search_result_title}}", search_result_title or ""),
            ("{{first_search_result_snippet}}", search_result_snippet or ""),
            ("{{first_search_result}}", str({
                "url": search_result_url,
                "title": search_result_title,
                "snippet": search_result_snippet
            }) if search_result_url else ""),
            ("{{last_tool_result}}", str(last_tool_result) if last_tool_result else ""),
            ("{{last_tool_result_url}}", search_result_url or ""),
            # 格式二：单花括号 {...}
            ("{first_search_result_url}", search_result_url or ""),
            ("{first_search_result_title}", search_result_title or ""),
            ("{first_search_result_snippet}", search_result_snippet or ""),
            ("{first_search_result}", str({
                "url": search_result_url,
                "title": search_result_title,
                "snippet": search_result_snippet
            }) if search_result_url else ""),
            ("{last_tool_result}", str(last_tool_result) if last_tool_result else ""),
            ("{last_tool_result_url}", search_result_url or ""),
        ]
        
        # 对 params 中的每个参数进行占位符替换
        if hasattr(resolved_step, 'params') and resolved_step.params:
            for key, value in resolved_step.params.items():
                if isinstance(value, str):
                    original_value = value
                    for placeholder, replacement in replacements:
                        if placeholder in value:
                            value = value.replace(placeholder, replacement)
                    
                    # 只有值发生变化时才记录日志
                    if original_value != value:
                        logger.info(
                            f"{Fore.GREEN}[占位符替换] 参数 '{key}': "
                            f"'{original_value[:80]}' -> '{value[:80]}'{Style.RESET_ALL}"
                        )
                    
                    resolved_step.params[key] = value
                elif isinstance(value, dict):
                    # 递归处理字典类型的参数值
                    resolved_step.params[key] = self._resolve_dict_placeholders(value, dict(replacements))
        
        return resolved_step

    def _resolve_dict_placeholders(
        self,
        data: Any,
        replacements
    ) -> Any:
        """
        递归解析字典中的占位符
        
        Args:
            data: 需要处理的数据（可能是 dict, list, str 等）
            replacements: 占位符替换映射（可以是 dict 或 list of tuples）
            
        Returns:
            处理后的数据
        """
        import copy
        
        # 统一转换为 list 格式
        if isinstance(replacements, dict):
            replacements_list = list(replacements.items())
        else:
            replacements_list = replacements
        
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                result[key] = self._resolve_dict_placeholders(value, replacements_list)
            return result
        elif isinstance(data, list):
            return [self._resolve_dict_placeholders(item, replacements_list) for item in data]
        elif isinstance(data, str):
            for placeholder, replacement in replacements_list:
                if placeholder in data:
                    data = data.replace(placeholder, replacement)
            return data
        else:
            return data

    async def _execute_step(
        self,
        agent: Agent,
        step: PlanStep,
        context: Optional[Dict[str, Any]] = None,
        prev_results: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        执行单个步骤

        Args:
            agent: Agent 实例
            step: 计划步骤
            context: 执行上下文
            prev_results: 本轮已完成步骤的结果列表，供 skill 等引用真实数据

        Returns:
            Dict[str, Any]: 步骤执行结果
        """
        try:
            if step.action == "tool":
                return await self._execute_tool(step, agent)
            elif step.action == "skill":
                return await self._execute_skill(step, context, agent, prev_results)
            elif step.action == "delegate":
                # 把 context 也传给委派方法，以便透传 stream_callback / pending_confirmations
                return await self._delegate_to_agent(step, context, prev_results)
            elif step.action == "final_answer":
                return {
                    "success": True,
                    "result": step.params.get("content", ""),
                    "action": "final_answer"
                }
            else:
                # ── 兜底兼容：LLM 有时把工具名直接写成 action（如 "database_query"）
                # 检查 action 值是否是已注册的工具名，若是则自动修正为 action="tool"
                if self.tool_hub and self.tool_hub.get_tool(step.action):
                    original_action = step.action
                    logger.warning(
                        f"{Fore.YELLOW}[兼容] LLM 将工具名 '{original_action}' "
                        f"误用为 action 类型，自动修正为 action='tool'{Style.RESET_ALL}"
                    )
                    # 若 params 中没有 tool_name 则补充（有的话直接用）
                    if "tool_name" not in step.params:
                        step.params["tool_name"] = original_action
                    step.action = "tool"
                    return await self._execute_tool(step, agent)
                
                logger.warning(
                    f"{Fore.YELLOW}未知的 action 类型: {step.action}{Style.RESET_ALL}"
                )
                return {
                    "success": False,
                    "error": f"未知的 action 类型: {step.action}"
                }
                
        except Exception as e:
            logger.error(
                f"{Fore.RED}执行步骤时发生错误 (action={step.action}): {e}{Style.RESET_ALL}"
            )
            return {
                "success": False,
                "error": str(e),
                "action": step.action
            }
    
    async def _execute_tool(
        self, step: PlanStep, agent: Optional[Agent] = None
    ) -> Dict[str, Any]:
        """
        执行工具调用

        Args:
            step: 计划步骤
            agent: 当前 Agent 实例（用于授权校验）

        Returns:
            Dict[str, Any]: 执行结果
        """
        tool_name = step.params.get("tool_name")
        params = step.params.get("params", {})
        
        logger.info(f"{Fore.CYAN}调用工具: {tool_name}{Style.RESET_ALL}")

        # ── 工具授权校验 ──────────────────────────────────────────
        # 若 agent 声明了 available_tools（非空），则只允许使用授权内的工具
        if agent and agent.available_tools and tool_name not in agent.available_tools:
            error_msg = (
                f"Agent '{agent.name}' 无权使用工具 '{tool_name}'。"
                f"该 Agent 仅授权以下工具: {agent.available_tools}。"
                f"如需使用 '{tool_name}'，请委派给有该工具权限的子 Agent。"
            )
            logger.warning(f"{Fore.YELLOW}[权限拦截] {error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": error_msg,
                "action": "tool",
                "tool_name": tool_name
            }
        
        # 检查工具是否存在（无论走网关还是直接调用都需要先验证）
        tool = self.tool_hub.get_tool(tool_name)
        if not tool:
            error_msg = f"工具不存在: {tool_name}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": error_msg,
                "action": "tool",
                "tool_name": tool_name
            }
        
        # ── 路径一：通过 ToolCallingGateway 执行（推荐路径）─────────────────
        # 当网关已配置时，所有工具调用统一走网关，享受：
        #   - 参数 JSON Schema 校验（防止非法参数进入工具）
        #   - 超时控制（避免工具阻塞整个 Agent 流程）
        #   - 执行统计（call_count / success_rate / avg_time 等）
        #   - 统一错误处理和日志追踪
        if self.tool_gateway:
            try:
                logger.info(
                    f"{Fore.BLUE}[执行引擎→网关] 通过 ToolCallingGateway 执行工具: "
                    f"{tool_name}{Style.RESET_ALL}"
                )
                # 调用网关的直接执行方法（规划执行模式专用，无需构造 LLM 格式响应）
                from app.llm_hub.tool_gateway import ToolCallStatus
                gateway_result = await self.tool_gateway.execute_direct_tool_call(
                    tool_name=tool_name,
                    arguments=params
                )
                
                if gateway_result.status == ToolCallStatus.SUCCESS:
                    logger.info(
                        f"{Fore.GREEN}[执行引擎←网关] 工具 {tool_name} 执行成功，"
                        f"耗时: {gateway_result.execution_time_ms:.2f}ms{Style.RESET_ALL}"
                    )
                    return {
                        "success": True,
                        "result": gateway_result.result,
                        "action": "tool",
                        "tool_name": tool_name,
                        # 附加网关统计信息，供调试和监控使用
                        "execution_time_ms": gateway_result.execution_time_ms
                    }
                else:
                    error_msg = (
                        f"工具 {tool_name} 通过网关执行失败 "
                        f"(status={gateway_result.status.value}): {gateway_result.error}"
                    )
                    logger.warning(f"{Fore.YELLOW}{error_msg}{Style.RESET_ALL}")
                    return {
                        "success": False,
                        "error": error_msg,
                        "action": "tool",
                        "tool_name": tool_name
                    }
            except Exception as e:
                # 网关执行出现意外异常时，降级到直接调用，保证 Agent 流程不中断
                logger.warning(
                    f"{Fore.YELLOW}[执行引擎] 网关执行异常，降级为直接调用: {e}{Style.RESET_ALL}"
                )
                # 降级执行（fall-through 到下面的直接调用代码）
                try:
                    result = await tool.execute(params)
                    logger.info(
                        f"{Fore.GREEN}[执行引擎] 工具 {tool_name} 降级直接调用成功{Style.RESET_ALL}"
                    )
                    return {
                        "success": True,
                        "result": result,
                        "action": "tool",
                        "tool_name": tool_name
                    }
                except Exception as fallback_e:
                    error_msg = f"工具 {tool_name} 降级执行也失败: {fallback_e}"
                    logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
                    return {
                        "success": False,
                        "error": str(fallback_e),
                        "action": "tool",
                        "tool_name": tool_name
                    }
        
        # ── 路径二：直接调用（未配置网关时的降级路径）────────────────────────
        try:
            result = await tool.execute(params)
            logger.info(f"{Fore.GREEN}工具 {tool_name} 执行成功{Style.RESET_ALL}")
            
            return {
                "success": True,
                "result": result,
                "action": "tool",
                "tool_name": tool_name
            }
        except Exception as e:
            error_msg = f"工具 {tool_name} 执行失败: {e}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": str(e),
                "action": "tool",
                "tool_name": tool_name
            }
    
    async def _execute_skill(
        self,
        step: PlanStep,
        context: Optional[Dict[str, Any]] = None,
        agent: Optional[Agent] = None,
        prev_results: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        执行技能调用

        Args:
            step: 计划步骤
            context: 执行上下文
            agent: 当前 Agent 实例
            prev_results: 本轮已完成步骤的结果列表，用于向 skill 注入真实数据

        Returns:
            Dict[str, Any]: 执行结果
        """
        skill_id = step.params.get("skill_id")
        params = step.params.get("params", {})
        
        # ====== 【调试日志】显示技能调用前的参数 ======
        logger.info(f"{Fore.CYAN}调用技能: {skill_id}, 原始参数: {params}{Style.RESET_ALL}")
        
        # 获取技能
        skill = self.skill_manager.get_skill(skill_id)
        if not skill:
            error_msg = f"技能不存在: {skill_id}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": error_msg,
                "action": "skill",
                "skill_id": skill_id
            }
        
        # 执行技能（通过 LLM）
        try:
            # 1. 准备参数，添加默认值以增强鲁棒性
            safe_params = params.copy()
            
            # ── 将前序步骤的真实数据注入 skill 参数 ────────────────
            # LLM 在规划阶段无法知道工具结果，skill 的 data/content 往往是描述文字。
            # 如果存在真实的工具/委派执行结果，用它们替换或补充 skill 的数据输入。
            if prev_results:
                real_data_parts = []
                for r in prev_results:
                    if not (r.get("success") and r.get("result")):
                        continue
                    label = r.get("tool_name") or r.get("agent_id") or r.get("action", "")
                    val = r["result"]
                    if isinstance(val, dict):
                        val_str = _json.dumps(val, ensure_ascii=False, indent=2)
                    else:
                        val_str = str(val)
                    if len(val_str) > 2000:
                        val_str = val_str[:2000] + "\n...（已截断）"
                    real_data_parts.append(f"[{label}]\n{val_str}")
                
                if real_data_parts:
                    injected_data = "\n\n".join(real_data_parts)
                    
                    # ====== 【关键修复】先进行占位符替换 ======
                    # 将 params 中的所有占位符替换为真实数据
                    for key in safe_params:
                        if isinstance(safe_params[key], str):
                            original = safe_params[key]
                            # 先替换占位符（支持双花括号和单花括号格式）
                            for placeholder, replacement in [
                                ("{{last_tool_result}}", injected_data),
                                ("{last_tool_result}", injected_data),
                                ("{{first_search_result}}", injected_data),
                                ("{first_search_result}", injected_data),
                            ]:
                                if placeholder in safe_params[key]:
                                    safe_params[key] = safe_params[key].replace(placeholder, replacement)
                                    logger.info(
                                        f"{Fore.GREEN}[技能数据注入] 参数 '{key}': "
                                        f"'{original[:50]}...' 已替换为真实数据{Style.RESET_ALL}"
                                    )
                                    break  # 找到一个匹配就退出，避免重复替换
                    
                    # 对于需要数据输入的技能（data_analysis 等），用真实数据替换描述
                    if skill_id in ("data_analysis",):
                        safe_params["data"] = injected_data
                        logger.info(
                            f"{Fore.BLUE}[执行引擎] 向技能 {skill_id} 注入前序步骤真实数据"
                            f"（{len(real_data_parts)} 条）{Style.RESET_ALL}"
                        )
                    # 通用：若参数里有 content/topic/input/text 是简短描述，也追加真实数据
                    for key in ("content", "topic", "input", "text", "task", "source_text"):
                        if key in safe_params and isinstance(safe_params[key], str):
                            # 如果包含换行符，说明已经是长文本（可能是已替换的数据），不再追加
                            if "\n" not in safe_params[key] and len(safe_params[key]) < 200:
                                safe_params[key] = safe_params[key] + "\n\n" + injected_data
                                logger.info(
                                    f"{Fore.BLUE}[执行引擎] 向技能 {skill_id} 的参数 '{key}' "
                                    f"追加前序步骤真实数据{Style.RESET_ALL}"
                                )
                                break
            
            # 通用回退逻辑：如果缺 topic 用 content，反之亦然
            if "topic" not in safe_params and "content" in safe_params:
                safe_params["topic"] = safe_params["content"]
            if "content" not in safe_params and "topic" in safe_params:
                safe_params["content"] = safe_params["topic"]
                
            # 针对 text_writing 技能的特定默认值
            if skill_id == "text_writing":
                if "topic" not in safe_params:
                    safe_params["topic"] = "未指定主题"
                if "content_type" not in safe_params:
                    safe_params["content_type"] = "一般文本"
                if "style" not in safe_params:
                    safe_params["style"] = "清晰自然"
                if "word_count" not in safe_params:
                    safe_params["word_count"] = "适中"

            # 2. 构建 Prompt
            try:
                prompt = skill.prompt_template.format(**safe_params)
            except KeyError as e:
                logger.warning(
                    f"{Fore.YELLOW}技能 Prompt 格式化缺少参数: {e}，使用通用 Prompt{Style.RESET_ALL}"
                )
                # 兜底 Prompt
                prompt_params_str = "\n".join([f"{k}: {v}" for k, v in params.items()])
                prompt = f"""请执行技能"{skill.name}"的任务。
                
任务描述:
{skill.description}

输入参数:
{prompt_params_str}

请直接输出执行结果。
"""
            
            from app.llm_hub.inference import InferenceConfig
            
            # 优先使用 agent 配置的模型，否则回退到默认
            model = "gpt-3.5-turbo"
            if agent and agent.agent_config:
                model = agent.agent_config.execution_model
            
            # 获取工具定义（用于 LLM function calling）
            tools = self.tool_hub.get_schemas()
            logger.debug(f"{Fore.CYAN}[执行引擎] 技能执行 - 已注册 {len(tools)} 个工具定义{Style.RESET_ALL}")
            
            config = InferenceConfig(
                model=model,
                temperature=0.7,
                tools=tools
            )
            
            response = await self.llm_hub.infer(
                messages=[{"role": "user", "content": prompt}],
                config=config
            )
            
            logger.info(f"{Fore.GREEN}技能 {skill_id} 执行成功{Style.RESET_ALL}")
            
            return {
                "success": True,
                "result": response.content,
                "action": "skill",
                "skill_id": skill_id
            }
            
        except Exception as e:
            error_msg = f"技能 {skill_id} 执行失败: {e}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": str(e),
                "action": "skill",
                "skill_id": skill_id
            }
    
    async def _delegate_to_agent(
        self,
        step: PlanStep,
        context: Optional[Dict[str, Any]] = None,
        prev_results: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        委派给子 Agent

        Args:
            step: 计划步骤
            context: 执行上下文（透传 stream_callback / pending_confirmations 以便
                     子 Agent 也能推送 user_confirm_required 事件并共享确认映射表）
            prev_results: 本轮已完成步骤结果，用于把上游真实数据注入子 Agent 任务

        Returns:
            Dict[str, Any]: 执行结果
        """
        agent_id = step.params.get("agent_id")
        task = step.params.get("task")
        if not isinstance(task, str):
            task = str(task or "")

        logger.info(f"{Fore.CYAN}委派任务给子 Agent: {agent_id}{Style.RESET_ALL}")

        if not self.child_agent_manager:
            error_msg = "子 Agent 管理器未初始化"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": error_msg,
                "action": "delegate",
                "agent_id": agent_id
            }

        # ── 向子 Agent 任务注入上游真实结果，避免“根据查询结果”却拿不到查询数据 ─────────
        # 典型场景：先 order_agent 查订单，再 general_agent 写文件。
        # 若不注入，general_agent 只能基于空上下文臆造价格内容。
        if prev_results:
            successful_prev = [
                r for r in prev_results
                if r.get("success") and (r.get("result") is not None)
            ]
            if successful_prev:
                def _to_text(value: Any, max_len: int = 2200) -> str:
                    if isinstance(value, (dict, list)):
                        s = _json.dumps(value, ensure_ascii=False, indent=2)
                    else:
                        s = str(value)
                    if len(s) > max_len:
                        s = s[:max_len] + "\n...（内容已截断）"
                    return s

                # 仅注入最近几条成功结果，控制上下文体积
                recent = successful_prev[-3:]
                blocks = []
                for r in recent:
                    label = r.get("tool_name") or r.get("skill_id") or r.get("agent_id") or r.get("action", "上游步骤")
                    payload = r.get("result")
                    # 委派结果携带子 Agent 轨迹，供下游精准复用（如提取价格后写文件）
                    if r.get("action") == "delegate":
                        payload = {
                            "agent_id": r.get("agent_id"),
                            "result": r.get("result"),
                            "step_results": r.get("step_results", []),
                            "error": r.get("error"),
                        }
                    blocks.append(f"[{label}]\n{_to_text(payload)}")
                upstream_context = "\n\n".join(blocks)

                # 若任务模板中已使用占位符则替换；否则直接追加显式上下文
                last_payload = successful_prev[-1].get("result")
                last_payload_text = _to_text(last_payload)
                replacements = [
                    ("{{last_tool_result}}", last_payload_text),
                    ("{last_tool_result}", last_payload_text),
                    ("{{upstream_results}}", upstream_context),
                    ("{upstream_results}", upstream_context),
                ]
                replaced = False
                for placeholder, value in replacements:
                    if placeholder in task:
                        task = task.replace(placeholder, value)
                        replaced = True

                if not replaced:
                    task = (
                        f"{task}\n\n"
                        "【上游已执行结果（必须基于真实结果继续执行，禁止臆造）】\n"
                        f"{upstream_context}"
                    )

                logger.info(
                    f"{Fore.BLUE}[委派] 已向子 Agent {agent_id} 注入上游结果，"
                    f"条数={len(recent)}{Style.RESET_ALL}"
                )

        # 从 context 中提取父级流式回调和挂起确认映射表
        # 这两个对象需要透传给子 Agent，使子 Agent：
        #   1. 也能向同一条 SSE 流推送 user_confirm_required 等事件
        #   2. 注册到父级的 pending_confirmations 字典，使 /agents/confirm 接口能够找到
        stream_callback = context.get("stream_callback") if context else None
        pending_confirmations = context.get("pending_confirmations") if context else None

        if stream_callback:
            logger.info(
                f"{Fore.BLUE}[委派] 检测到父级 stream_callback，"
                f"子 Agent {agent_id} 将共享 SSE 流和 pending_confirmations{Style.RESET_ALL}"
            )
        else:
            logger.info(
                f"{Fore.YELLOW}[委派] 无父级 stream_callback，"
                f"子 Agent {agent_id} 将以静默模式执行（无用户确认交互）{Style.RESET_ALL}"
            )

        # 委派任务（parent_agent_id 设为 None，因为在执行引擎层面不跟踪父 Agent）
        try:
            result = await self.child_agent_manager.delegate_task(
                parent_agent_id=None,
                child_agent_id=agent_id,
                task=task,
                stream_callback=stream_callback,          # 透传父级流式回调
                pending_confirmations=pending_confirmations  # 透传父级挂起确认表
            )
            
            logger.info(
                f"{Fore.GREEN}子 Agent {agent_id} 任务执行完成{Style.RESET_ALL}"
            )
            
            return {
                "success": True,
                "result": result,
                "action": "delegate",
                "agent_id": agent_id
            }
            
        except Exception as e:
            error_msg = f"委派给 Agent {agent_id} 失败: {e}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": str(e),
                "action": "delegate",
                "agent_id": agent_id
            }


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Execution Engine 测试{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
    
    # 测试执行结果
    result = ExecutionResult(
        success=True,
        result="测试成功",
        step_results=[{"action": "tool", "result": "ok"}]
    )
    print(f"创建执行结果: {result.to_dict()}")
    
    print(f"\n{Fore.GREEN}测试完成!{Style.RESET_ALL}\n")
