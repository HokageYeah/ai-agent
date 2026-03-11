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
from typing import Dict, List, Any, Optional, Callable, Awaitable
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
        error: Optional[str] = None,
        user_rejected_tools: Optional[List[str]] = None
    ):
        """
        初始化执行结果
        
        Args:
            success: 是否成功
            result: 最终结果
            step_results: 每个步骤的执行结果
            error: 错误信息
            user_rejected_tools: 用户已拒绝的工具列表
        """
        self.success = success
        self.result = result
        self.step_results = step_results or []
        self.error = error
        self.user_rejected_tools = user_rejected_tools or []
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "result": self.result,
            "step_results": self.step_results,
            "error": self.error,
            "user_rejected_tools": self.user_rejected_tools
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
        context: Optional[Dict[str, Any]] = None,
        on_step_complete: Optional[Callable[[Dict[str, Any], int, int], Awaitable[None]]] = None
    ) -> ExecutionResult:
        """
        执行计划

        Args:
            agent: Agent 实例
            plan: 执行计划
            context: 执行上下文
            on_step_complete: 【新增】步骤完成实时回调，签名为 async (step_result, step_idx, step_total) -> None。
                用于在每个步骤完成后立即推送 SSE 事件，解决以下问题：
                - 若在 execute_plan 外部（如 _execute_node）遍历 step_results 后批量推送事件，
                  会造成 sub_agent_start/end 事件（委派期间内部推送）早于 tool_complete 事件出现，
                  导致前端看到「先委派后查询」的错误顺序。
                - 通过在每步完成后立即回调，保证 tool_complete 紧跟在 sub_agent_start 之前推送。
            
        Returns:
            ExecutionResult: 执行结果
        """
        logger.info(
            f"{Fore.BLUE}开始执行计划，共 {len(plan.steps)} 个步骤{Style.RESET_ALL}"
        )
        
        step_results = []
        final_result = None
        step_total = len(plan.steps)
        # ── 新增: 初始化用户已拒绝工具黑名单 ──────────────────────────────
        # 继承父级传来的 user_rejected_tools，防止重复尝试已被拒绝的工具。
        user_rejected_tools = list(context.get("user_rejected_tools", [])) if context else []
        
        try:
            for i, step in enumerate(plan.steps, 1):
                logger.info(
                    f"{Fore.CYAN}执行步骤 {i}/{step_total}: "
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
                
                # ── 新增: 合并子层级返回的 user_rejected_tools ────────────────
                # 不论是本层直接调用工具被拒，还是嵌套的子 Agent 中工具被拒，
                # 都需不断向父层冒泡累积，防止不同层级的重新规划尝试同一条死路。
                if "user_rejected_tools" in step_result:
                    for t in step_result["user_rejected_tools"]:
                        if t not in user_rejected_tools:
                            user_rejected_tools.append(t)
                            
                step_results.append(step_result)

                # ═══════════════════════════════════════════════════════════════
                # 【实时 SSE 事件推送】步骤完成后立即回调，保证事件顺序正确。
                #
                # 设计动机：
                #   子Agent委派（delegate）期间，child_agent_manager 内部会直接通过
                #   stream_callback 推送 sub_agent_start/end 及子Agent全部内部事件。
                #   若等到 execute_plan 返回后才在 _execute_node 中遍历批量推送
                #   tool_complete/delegate_complete，则这些事件会晚于 sub_agent_end 到达，
                #   造成前端看到「先委派后查询」的假象。
                #
                #   通过在此处调用 on_step_complete，保证：
                #   Step1(tool)完成 → 立即推送 tool_complete
                #   Step2(delegate)期间 → 推送 sub_agent_start/内部事件/sub_agent_end
                #   Step2(delegate)完成 → 立即推送 delegate_complete
                #   顺序完全还原为规划设计的真实执行顺序。
                # ═══════════════════════════════════════════════════════════════
                if on_step_complete and step.action != "final_answer":
                    # final_answer 步骤的合成在下方进行，等合成完毕再回调
                    logger.debug(
                        f"{Fore.CYAN}[执行引擎] 步骤 {i}/{step_total} 完成，触发实时事件回调 "
                        f"(action={step.action}){Style.RESET_ALL}"
                    )
                    await on_step_complete(step_result, i, step_total)
                
                # 如果是 final_answer，先合成再返回
                if step.action == "final_answer":
                    template = step.params.get("content", "")
                    
                    # 收集本轮所有成功的工具/技能/委派结果（排除 final_answer 步骤本身）
                    tool_results = [
                        r for r in step_results
                        if r.get("success") and r.get("result")
                        and r.get("action") != "final_answer"
                    ]
                    
                    # ══════════════════════════════════════════════════════════
                    # 【合成策略判断】LLM 规划的 final_answer.content 有两种情况：
                    # - 情况A（有工具前置）：content 只是意图描述 → 用工具结果 LLM 合成
                    # - 情况B（纯记忆问答）：LLM 理应在 content 写出真实答案，
                    #   但有时仍会写意图描述（如"根据历史记录回答..."）→ 需要兜底合成
                    # ══════════════════════════════════════════════════════════
                    
                    # 判断 content 是否是"意图描述"而非真实自然语言答案
                    # 意图描述的特征：包含"根据"/"历史"/"回答用户"/"以上"等指令性词汇，
                    # 且不包含具体信息（通常较短）
                    def _is_intent_description(content: str) -> bool:
                        """判断 content 是否是意图/占位符描述，而非真实答案"""
                        if not content:
                            return True
                        intent_keywords = [
                            "根据历史", "根据以上", "根据上面", "根据前面",
                            "回答用户", "回答关于", "回答该", "回答此",
                            "结合历史", "参考历史", "基于历史",
                            "用户关于", "告知用户",
                            "查询结果回答", "执行结果回答",
                        ]
                        # 短内容（<30字）且包含意图关键词 → 判断为意图描述
                        if len(content) < 80:
                            for kw in intent_keywords:
                                if kw in content:
                                    return True
                        return False
                    
                    # 获取会话历史上下文（用于兜底合成）
                    context_messages = (context or {}).get("context_messages", [])
                    
                    if bool(tool_results):
                        # 情况A：有前置工具结果 → 用工具结果驱动 LLM 合成
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
                    elif context_messages and _is_intent_description(template):
                        # ══════════════════════════════════════════════════════
                        # 【兜底安全网】情况B：计划只有 final_answer 一步，
                        # 且 LLM 仍然写了意图描述而非真实答案。
                        # 此时用会话历史 context_messages 重新触发 LLM 直接合成真实答案，
                        # 防止把意图描述文本（如"根据历史记录回答..."）直接返回给用户。
                        # ══════════════════════════════════════════════════════
                        logger.warning(
                            f"{Fore.YELLOW}[执行引擎] 检测到纯 final_answer 场景，"
                            f"且 content 为意图描述（'{template[:50]}'）。"
                            f"存在会话历史上下文（{len(context_messages)} 条），"
                            f"触发兜底 LLM 合成真实答案...{Style.RESET_ALL}"
                        )
                        final_result = await self._synthesize_from_context(
                            agent=agent,
                            task=context.get("task", "") if context else "",
                            context_messages=context_messages,
                        )
                    elif template:
                        logger.info(
                            f"{Fore.CYAN}[执行引擎] 直接使用 final_answer.content 作为最终结果"
                            f"（长度={len(template)}）{Style.RESET_ALL}"
                        )
                        final_result = template
                    else:
                        final_result = "执行完成，但没有产生具体结果。"

                    logger.info(
                        f"{Fore.GREEN}执行完成，获得最终答案{Style.RESET_ALL}"
                    )
                    
                    # final_answer 步骤也触发实时回调（合成完成后再推送，保证数据完整性）
                    if on_step_complete:
                        logger.debug(
                            f"{Fore.CYAN}[执行引擎] final_answer 步骤合成完毕，触发实时事件回调 "
                            f"(step={i}/{step_total}){Style.RESET_ALL}"
                        )
                        await on_step_complete(step_result, i, step_total)
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
                step_results=step_results,
                user_rejected_tools=user_rejected_tools
            )
            
        except Exception as e:
            logger.error(f"{Fore.RED}执行计划时发生错误: {e}{Style.RESET_ALL}")
            
            return ExecutionResult(
                success=False,
                result=None,
                step_results=step_results,
                error=str(e),
                user_rejected_tools=user_rejected_tools
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
            elif r.get("tool_name") == "python_executor" and isinstance(r.get("result"), dict):
                res = r.get("result") or {}
                val = {
                    "success": res.get("success"),
                    "result": res.get("result"),
                    "output": res.get("output"),
                    "error": res.get("error"),
                }
                if res.get("output"):
                    val["_hint"] = "以上 output 为 python_executor 的输出。若为一段可运行的 Python 脚本（替用户生成写文件用），请在最终回答中完整贴出脚本并说明用户保存为 .py 后运行即可；若为普通文本则完整包含即可。"
            else:
                val = r.get("result", "")
            if isinstance(val, dict):
                val_str = _json.dumps(val, ensure_ascii=False, indent=2, default=str)
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
5. 【重要防幻觉】如果任务包含“写入本地文件/保存到文件”等需求，你必须**严格检查上方数据中是否有 `file_write` 工具的执行成功结果**。
   - 如果**有** `file_write` 工具且执行成功：说明写入成功、写入路径与写入内容来源。
   - 如果**没有** `file_write` 工具的结果：你**绝对不能**说"已入写本地文件"或"已保存到文件"。对于只有 `text_writing` 技能的结果，请只返回生成的文本内容，不要编造任何本地文件路径。
6. **若执行结果来自 python_executor 且为“替用户生成写文件的脚本”**（例如因用户拒绝了 file_write）：若工具返回中有 output 且为一段 Python 代码/脚本，最终回答必须**完整贴出**该 output 的全文（即可运行的脚本），并说明「因您拒绝了由系统直接写入文件，已为您生成以下可本地运行的 Python 脚本。请将下方代码保存为 .py 文件（如 save_content.py）后在本地执行，即可在当前目录生成文件。」禁止只做概括或省略脚本内容。

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
                + (_json.dumps(r["result"], ensure_ascii=False, indent=2, default=str)
                   if isinstance(r["result"], dict) else str(r["result"]))
                for r in tool_results
                if r.get("result")
            ) or template or "执行完成，但未能生成最终答案。"

    async def _synthesize_from_context(
        self,
        agent: Agent,
        task: str,
        context_messages: List[Dict[str, Any]],
    ) -> str:
        """
        【兜底合成】基于会话历史上下文（context_messages）用 LLM 直接生成答案。

        当计划只有 final_answer 一步（纯记忆问答场景），且 LLM 写了意图描述而非真实答案时，
        此方法作为兜底安全网被调用，利用注入的历史会话摘要让 LLM 给出真正的自然语言回答。

        设计原因：
        - 规划 Prompt 已要求 LLM 在情况A（无工具）时把 final_answer.content 写成真实答案
        - 但由于 LLM 惯性，仍可能写出意图描述（"根据历史记录回答..."）
        - 此方法作为最后防线，确保最终用户收到的是具体答案而非意图描述

        Args:
            agent: 当前执行的 Agent 实例
            task: 原始用户任务描述
            context_messages: 会话历史消息列表（含历史任务摘要等上下文）

        Returns:
            str: 基于历史上下文合成的自然语言答案
        """
        logger.info(
            f"{Fore.BLUE}[执行引擎] 开始基于会话历史上下文兜底合成答案，"
            f"上下文消息数量: {len(context_messages)}{Style.RESET_ALL}"
        )

        # 将历史上下文消息格式化为文本，供 LLM 参考
        context_text_parts = []
        for msg in context_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if not content:
                continue
            # 截断超长消息，防止 token 超限
            if len(str(content)) > 1500:
                content = str(content)[:1500] + "...(已截断)"
            if role == "system":
                context_text_parts.append(f"[系统上下文]\n{content}")
            elif role == "user":
                context_text_parts.append(f"[用户]\n{content}")
            elif role == "assistant":
                context_text_parts.append(f"[助手]\n{content}")

        context_text = "\n\n---\n\n".join(context_text_parts) if context_text_parts else "（无可用上下文）"

        synthesis_prompt = f"""你是 {agent.name}，{agent.description}

用户当前的问题（任务）：{task}

以下是本次会话的历史上下文信息（包含之前各轮任务的摘要）：

{context_text}

请根据以上历史上下文，直接、准确地回答用户的问题。
要求：
1. 基于历史信息给出具体、完整的回答，不要模糊或含糊其辞
2. 如果历史上下文中有明确的信息，直接陈述（如"您第一次的提问是'xxx'，任务是yyy"）
3. 语言简洁友好，格式清晰
4. 如果历史记录中确实没有相关信息，如实告知

请直接输出最终回答，不要包含任何前缀说明。"""

        try:
            from app.llm_hub.inference import InferenceConfig

            config = InferenceConfig(
                model=agent.agent_config.execution_model,
                stream=False,
                temperature=0.2,   # 记忆召回用极低温度，确保精准引用历史信息
            )
            response = await self.llm_hub.infer(
                messages=[{"role": "user", "content": synthesis_prompt}],
                config=config
            )
            answer = response.content.strip()
            logger.info(
                f"{Fore.GREEN}[执行引擎] 兜底上下文合成完成，"
                f"答案长度: {len(answer)} 字符，"
                f"预览: {answer[:100]}{Style.RESET_ALL}"
            )
            return answer

        except Exception as e:
            logger.error(
                f"{Fore.RED}[执行引擎] 兜底上下文合成失败: {e}，"
                f"返回空结果{Style.RESET_ALL}"
            )
            return "抱歉，我无法根据历史记录找到相关信息，请重新描述您的问题。"

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
            
            # 记录最后一个工具/技能结果，作为 {{last_tool_result}} 的替换来源
            # NOTE: 同时覆盖 skill 类型，是因为 LLM 经常规划 text_writing(skill) → file_write(tool) 的两步链。
            # 若只记录 action=="tool"，则 text_writing 的输出永远不会成为 last_tool_result，
            # 导致 file_write 步骤的 content 参数占位符被替换为空字符串，触发"文件内容不能为 None"错误。
            if result.get("action") in ("tool", "skill"):
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
                # NOTE: 必须传入 context，否则 SpawnAgentTool / MessageAgentTool 等
                #       需要运行时注入 stream_callback 的工具将以 None 回调执行，
                #       导致子 Agent 事件无法推入 SSE 流、用户确认弹窗无法展示。
                return await self._execute_tool(step, agent, context)
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
                    # 同样传入 context，保证兜底路径下工具也能获得运行时上下文
                    return await self._execute_tool(step, agent, context)
                
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
        self,
        step: PlanStep,
        agent: Optional[Agent] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        执行工具调用

        Args:
            step:    计划步骤
            agent:   当前 Agent 实例（用于授权校验）
            context: 执行上下文（含 stream_callback / pending_confirmations 等运行时依赖）
                     对于 SpawnAgentTool、MessageAgentTool 等需要运行时注入的工具，
                     必须传入此参数，否则这类工具无法正确推送 SSE 事件。

        Returns:
            Dict[str, Any]: 执行结果

        NOTE 运行时上下文注入机制：
             部分工具（如 spawn_agent、send_message）在注册到 ToolHub 时尚无 stream_callback，
             需要在每次调用前通过 update_context() 注入当前执行上下文。
             本方法通过鸭子类型检测工具是否有 update_context 方法：
               - 有 → 在调用 execute() 前先注入 stream_callback / pending_confirmations
               - 无 → 普通工具，直接调用即可
        """
        tool_name = step.params.get("tool_name")
        params = step.params.get("params", {})

        logger.info(
            f"{Fore.CYAN}[执行工具] 准备调用工具: {tool_name} "
            f"| context={'已传入' if context else '未传入'}{Style.RESET_ALL}"
        )

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

        # ── 运行时上下文注入（context-aware 工具专用）────────────────────────
        # 工具如 spawn_agent / send_message 在注册时没有 stream_callback，
        # 每次调用前需要通过 update_context() 注入当前执行环境的运行时依赖：
        #   - stream_callback:      SSE 事件推送回调（子 Agent 事件透传给前端）
        #   - pending_confirmations: 挂起确认映射表（/agents/confirm 接口能找到对应确认）
        #   - user_rejected_tools:  已拒绝工具黑名单（子 Agent 回避重复尝试）
        # 通过鸭子类型检测 update_context，避免对工具类名硬编码（扩展性更强）
        if context and hasattr(tool, "update_context") and callable(tool.update_context):
            _stream_cb      = context.get("stream_callback")
            _pending_confs  = context.get("pending_confirmations")
            _rejected_tools = context.get("user_rejected_tools")
            tool.update_context(
                stream_callback       = _stream_cb,
                pending_confirmations = _pending_confs,
                user_rejected_tools   = _rejected_tools,
            )
            logger.info(
                f"{Fore.GREEN}[执行工具] 已为工具 '{tool_name}' 注入运行时上下文 "
                f"| stream_callback={'✅ 已注入' if _stream_cb else '❌ 未传入，子Agent事件将无法推流'} "
                f"| pending_confirmations={'✅ 已注入' if _pending_confs else '⚠️ 未传入'}{Style.RESET_ALL}"
            )
        elif tool_name in ("spawn_agent", "send_message") and not context:
            # 对已知需要上下文的工具，发出明确警告
            logger.warning(
                f"{Fore.YELLOW}[执行工具⚠️] 工具 '{tool_name}' 需要运行时上下文（stream_callback 等），"
                f"但调用时未传入 context！子 Agent 的 SSE 事件将无法推入当前流。"
                f"请确保 _execute_step 正确传入 context 参数。{Style.RESET_ALL}"
            )

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
                        val_str = _json.dumps(val, ensure_ascii=False, indent=2, default=str)
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
            all_tools_schemas = self.tool_hub.get_schemas() if self.tool_hub else []
            tools = []
            
            # 敏感工具列表：禁止在技能内部隐式调用，必须由外层 Agent 在计划中显式调用以触发二次确认
            SENSITIVE_TOOLS = {"file_write"}
            
            # 过滤：只允许被授权的工具，排除敏感工具，并且排除用户已拒绝的工具
            user_rejected = context.get("user_rejected_tools", []) if context else []
            for t_schema in all_tools_schemas:
                t_name = t_schema.get("name")
                if agent and agent.available_tools and t_name not in agent.available_tools:
                    continue
                if t_name in SENSITIVE_TOOLS:
                    continue
                if t_name in user_rejected:
                    continue
                tools.append(t_schema)
                
            logger.debug(
                f"{Fore.CYAN}[执行引擎] 技能执行 - 过滤后提供 {len(tools)} 个工具定义"
                f"（排除拒绝工具: {user_rejected}，排除敏感工具: {SENSITIVE_TOOLS}）{Style.RESET_ALL}"
            )
            
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

        NOTE: 此方法包含防御性"需求完整性检查"：
              若规划阶段的 LLM 在生成 delegate task 时省略了原始用户需求中的
              文件写入、搜索等附加操作，此处会检测并发出 WARNING，
              并在子 Agent 的 task 末尾补充原始用户任务作为补救上下文。
        """
        agent_id = step.params.get("agent_id")
        task = step.params.get("task")
        if not isinstance(task, str):
            task = str(task or "")

        # ── 从 context 中提取原始用户任务（用于后续完整性诊断） ────────────────
        # NOTE: 原始任务是顶层用户输入，从 execution context 中传入；
        #       若 LLM 规划时截断了某些需求（如"写入本地"），可通过对比检测并补救
        original_task: str = context.get("task", "") if context else ""

        logger.info(
            f"{Fore.CYAN}[委派] 准备委派任务给子 Agent: {agent_id} "
            f"| 委派任务长度={len(task)}字符 "
            f"| 原始用户任务长度={len(original_task)}字符{Style.RESET_ALL}"
        )
        logger.debug(
            f"{Fore.BLUE}[委派] 委派任务摘要: {task[:150]}...{Style.RESET_ALL}"
        )
        if original_task:
            logger.debug(
                f"{Fore.BLUE}[委派] 原始用户任务摘要: {original_task[:150]}...{Style.RESET_ALL}"
            )

        # ── 防御性检查：委派任务是否遗漏了原始用户需求中的关键操作 ────────────
        # 典型遗漏场景：用户说"查询订单并写入本地"，LLM 规划只把"查询订单"
        # 传给 order_agent，把"写入本地"直接丢弃，导致子 Agent 不知道还需要写文件
        FILE_WRITE_KEYWORDS = ["写入本地", "保存文件", "写入文件", "保存到", "写到", "file_write"]
        if original_task:
            missing_keywords = []
            for kw in FILE_WRITE_KEYWORDS:
                # 原始任务中包含该关键词，但规划的委派 task 中没有
                if kw in original_task and kw not in task:
                    missing_keywords.append(kw)

            if missing_keywords:
                # 检测到需求可能被遗漏，发出警告日志并补充原始任务上下文
                logger.warning(
                    f"{Fore.YELLOW}[委派⚠️] 检测到委派任务可能遗漏了原始用户需求！"
                    f"\n  原始用户任务: '{original_task[:120]}'"
                    f"\n  委派的 task : '{task[:120]}'"
                    f"\n  疑似遗漏关键词: {missing_keywords}"
                    f"\n  🔧 已自动追加原始用户完整需求到委派 task 末尾，防止信息丢失。{Style.RESET_ALL}"
                )
                # 自动修复：将原始用户任务作为"完整需求上下文"补充到委派 task 末尾，
                # 让子 Agent 知道用户的完整意图，避免因 LLM 规划截断导致需求遗漏
                task = (
                    f"{task}\n\n"
                    "【⚠️ 完整用户需求（请务必全部完成，不要遗漏）】\n"
                    f"用户原始请求：{original_task}\n"
                    "注意：如任务包含文件写入、搜索等操作而你的工具不支持，"
                    "必须通过 spawn_agent 将任务连同已查到的数据转交给 general_agent 完成。"
                )
                logger.info(
                    f"{Fore.GREEN}[委派🔧] 已向子 Agent '{agent_id}' 补充原始需求上下文，"
                    f"修复后 task 长度={len(task)}字符{Style.RESET_ALL}"
                )
            else:
                logger.debug(
                    f"{Fore.GREEN}[委派✅] 委派任务完整性检查通过，未发现需求遗漏{Style.RESET_ALL}"
                )

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
                        s = _json.dumps(value, ensure_ascii=False, indent=2, default=str)
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
        user_rejected_tools_in = context.get("user_rejected_tools") if context else None

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

        # ═══════════════════════════════════════════════════════════════════
        # 【统一委派路径：优先通过已注册的 SpawnAgentTool 执行委派】
        #
        # 设计动机：
        #   系统中已在 ToolHub 注册了 SpawnAgentTool（spawn_agent 工具），
        #   所有子 Agent 委派应统一经过该工具，以便享受：
        #     - SpawnAgentTool 自身的参数校验和日志
        #     - 工具网关的统一统计和超时管理
        #     - 将来可在 SpawnAgentTool 层面扩展拦截/修改逻辑
        #
        #   当 LLM 生成 action="delegate" 计划步骤时，执行引擎也应走同一路径，
        #   而不是直接绕过 SpawnAgentTool 调用 ChildAgentManager。
        #
        # 备用路径：
        #   若 SpawnAgentTool 未注册（如测试环境）或调用失败，
        #   回退到直接调用 ChildAgentManager.delegate_task（保证向后兼容）。
        # ═══════════════════════════════════════════════════════════════════
        spawn_tool = self.tool_hub.get_tool("spawn_agent") if self.tool_hub else None

        if spawn_tool and hasattr(spawn_tool, "update_context") and callable(spawn_tool.update_context):
            # ── 路径一（推荐）：通过 SpawnAgentTool 委派 ──────────────────────
            # 先更新工具的运行时上下文（stream_callback / pending_confirmations）
            spawn_tool.update_context(
                stream_callback       = stream_callback,
                pending_confirmations = pending_confirmations,
                user_rejected_tools   = user_rejected_tools_in,
            )
            logger.info(
                f"{Fore.GREEN}[委派→SpawnAgentTool] 通过已注册的 spawn_agent 工具委派任务 "
                f"→ {agent_id} | stream_callback={'✅ 已注入' if stream_callback else '❌ 未传入'}"
                f"{Style.RESET_ALL}"
            )
            try:
                result = await spawn_tool.execute({
                    "agent_id": agent_id,
                    "task":     task,   # 已包含上游结果注入 + 原始需求补充
                })

                _sub_success = result.get("success", False)
                # NOTE: result 来自 execute_with_callback，结构为
                #   {"success": bool, "result": ExecutionResult.to_dict(), "error": str|None, ...}
                # 这里需要从内层 result 里提取真实的错误信息，供父 Agent 错误收集使用
                _sub_error = result.get("error") or (
                    # 内层 result 也可能有 error 字段（ExecutionResult.to_dict()）
                    result.get("result", {}).get("error") if isinstance(result.get("result"), dict) else None
                )
                logger.info(
                    f"{Fore.GREEN if _sub_success else Fore.YELLOW}"
                    f"[委派←SpawnAgentTool] 子 Agent '{agent_id}' 通过 spawn_agent 工具执行完毕 "
                    f"| success={_sub_success} | error={_sub_error or '无'}"
                    f"{Style.RESET_ALL}"
                )
                return {
                    "success": _sub_success,
                    "result":  result,
                    "error":   _sub_error,          # 失败时传递真实错误，避免 "Unknown error"
                    "action":  "delegate",
                    "agent_id": agent_id,
                    "user_rejected_tools": result.get("user_rejected_tools", []),
                }

            except Exception as e:
                # SpawnAgentTool 调用失败时降级到直接委派，不中断流程
                logger.warning(
                    f"{Fore.YELLOW}[委派⚠️] SpawnAgentTool 调用异常，回退直接委派: {e}{Style.RESET_ALL}"
                )
                # fall-through to direct delegation

        # ── 路径二（兜底）：直接通过 ChildAgentManager 委派 ──────────────────
        # 当 SpawnAgentTool 未注册（如测试环境）或上方调用失败时走此路径
        # NOTE: child_agent_manager 在此处一定非 None，因为函数顶部已做早期返回保护
        logger.info(
            f"{Fore.BLUE}[委派→ChildAgentManager] 通过 ChildAgentManager 直接委派任务 "
            f"→ {agent_id}（SpawnAgentTool 不可用，使用兜底路径）{Style.RESET_ALL}"
        )
        try:
            result = await self.child_agent_manager.delegate_task(
                parent_agent_id      = None,
                child_agent_id       = agent_id,
                task                 = task,
                stream_callback      = stream_callback,
                pending_confirmations = pending_confirmations,
                user_rejected_tools  = user_rejected_tools_in,
            )

            _sub_success = result.get("success", False)
            _sub_error   = result.get("error")
            logger.info(
                f"{Fore.GREEN if _sub_success else Fore.YELLOW}"
                f"[委派←ChildAgentManager] 子 Agent '{agent_id}' 执行完成 "
                f"| success={_sub_success}{Style.RESET_ALL}"
            )
            return {
                "success": _sub_success,   # 根据子 Agent 实际成功状态，不再硬编码 True
                "result":  result,
                "error":   _sub_error,     # 传递子 Agent 的错误信息
                "action":  "delegate",
                "agent_id": agent_id,
                "user_rejected_tools": result.get("user_rejected_tools", []),
            }

        except Exception as e:
            error_msg = f"委派给 Agent {agent_id} 失败: {e}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error":   str(e),
                "action":  "delegate",
                "agent_id": agent_id,
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
