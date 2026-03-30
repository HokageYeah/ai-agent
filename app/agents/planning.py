"""
规划引擎 (Planning Engine)
================================

本模块负责为 Agent 创建执行计划。

功能特点：
1. 基于任务和可用资源生成执行计划
2. 使用 LLM 进行智能规划
3. 支持工具、技能、子 Agent 的组合使用
4. 返回结构化的 JSON 计划
5. 支持 AgentRunMemory：历史记忆以 OpenAI messages 格式传递，无需文字拼接

作者: AI Agent Team
创建时间: 2026-02-15
更新时间: 2026-03-13（提示词抽离到 prompt/plan，使用 Jinja2 渲染）
"""

import ast
import json
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from colorama import Fore, Style
from loguru import logger

from app.agents.base import Agent
from app.skills.base import Skill
from app.tools.base import Tool
from app.utils.llm_output_parser import (
    extract_first_balanced_json_array,
    extract_first_balanced_json_object,
    extract_json_payload,
    strip_think_blocks,
)
from app.utils.prompt_manager import PromptManager

# NOTE: 使用 TYPE_CHECKING 避免循环导入；运行时通过函数参数类型注解字符串引用
if TYPE_CHECKING:
    from app.memory.agent_run_memory import AgentRunMemory


class PlanStep:
    """计划步骤"""

    def __init__(self, action: str, **kwargs):
        """
        初始化计划步骤

        Args:
            action: 动作类型 (tool, skill, delegate, final_answer)
            **kwargs: 动作参数
        """
        self.action = action
        self.params = kwargs

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "action": self.action,
            **self.params,
        }


class Plan:
    """执行计划"""

    def __init__(self, steps: List[PlanStep], reasoning: str = ""):
        """
        初始化执行计划

        Args:
            steps: 计划步骤列表
            reasoning: 推理过程
        """
        self.steps = steps
        self.reasoning = reasoning

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "steps": [step.to_dict() for step in self.steps],
            "reasoning": self.reasoning,
        }


class PlanningEngine:
    """
    规划引擎

    使用 LLM 为 Agent 生成执行计划
    """

    def __init__(self, llm_hub, tool_hub=None):
        """
        初始化规划引擎

        Args:
            llm_hub: LLM Hub 实例 (InferenceEngine)
            tool_hub: 工具中心实例（可选），用于获取工具定义
        """
        self.llm_hub = llm_hub
        self.tool_hub = tool_hub
        # NOTE: 规划提示词统一放在 prompt/plan 目录。
        self.prompt_manager = PromptManager(prompt_dir="app/prompt/plan")
        logger.info(f"{Fore.GREEN}规划引擎初始化完成{Style.RESET_ALL}")

    async def create_plan(
        self,
        agent: Agent,
        task: str,
        available_tools: List[Tool],
        available_skills: List[Skill],
        context: Optional[Dict[str, Any]] = None,
        error_context: Optional[List[Dict[str, Any]]] = None,
        reflection_history: Optional[List[Dict[str, Any]]] = None,
        # NOTE: AgentRunMemory 集成入参——当传入时，优先用 messages 格式传递历史记忆，
        #       而非把错误/反思历史文字拼接到 prompt，提升 LLM 对上下文的理解准确度。
        run_memory: Optional[Any] = None,
        iteration: int = 0,
        stream_callback: Optional[Any] = None,
    ) -> Plan:
        """
        创建执行计划

        若传入 run_memory，则优先使用 messages 格式传递历史记忆（推荐）；
        否则降级为文字拼接模式（向后兼容）。

        Args:
            agent: Agent 实例
            task: 任务描述
            available_tools: 可用工具列表
            available_skills: 可用技能列表
            context: 额外上下文信息（兼容旧逻辑）
            error_context: 上一轮执行失败的步骤信息列表（兼容旧逻辑）
            reflection_history: 历次迭代的反思结论列表（兼容旧逻辑）
            run_memory: AgentRunMemory 实例，记忆已按 OpenAI messages 格式存储
            iteration: 当前迭代轮次（0-indexed，用于过滤记忆消息）

        Returns:
            Plan: 执行计划
        """
        logger.info(f"{Fore.BLUE}开始为 Agent '{agent.name}' 创建执行计划{Style.RESET_ALL}")

        if error_context:
            logger.info(
                f"{Fore.YELLOW}[规划引擎] 本次为错误感知重规划，携带 {len(error_context)} 条错误记录{Style.RESET_ALL}"
            )
        if reflection_history:
            logger.info(
                f"{Fore.YELLOW}[规划引擎] 本次携带 {len(reflection_history)} 条历史反思记录，引导改进规划方向{Style.RESET_ALL}"
            )

        logger.info(f"{Fore.BLUE}调用 LLM 生成计划...{Style.RESET_ALL}")

        try:
            from app.llm_hub.inference import InferenceConfig

            tools = []
            if self.tool_hub and available_tools:
                # ── 第一层过滤：按 Agent 白名单过滤授权工具 ──────────────────────────────
                # 只把 Agent 配置中允许的工具传给 Planning LLM；
                # 此处过滤的是工具"是否授权给该 Agent"，与 planning_safe 无关。
                allowed_tool_names = {t.name for t in available_tools}
                all_schemas = self.tool_hub.get_schemas()
                authorized_tools = [
                    schema
                    for schema in all_schemas
                    if schema.get("function", {}).get("name") in allowed_tool_names
                ]
                logger.debug(
                    f"{Fore.CYAN}[规划引擎] 工具定义已过滤: "
                    f"授权 {len(authorized_tools)}/{len(all_schemas)} 个（过滤掉了未授权工具）{Style.RESET_ALL}"
                )

                # ── 第二层过滤：仅允许 planning_safe=True 的工具进入规划 tool-calling loop ──
                # 设计原因：
                # - Planning 阶段的 LLM 在生成 JSON 计划前，会进入 tool-calling loop
                #   主动调用工具来搜集信息（如 search、http_request、file_read）。
                # - 若不过滤，LLM 可能直接在规划阶段调用 skill_install、shell_exec
                #   等有副作用的工具，导致以下问题：
                #     1. 副作用已发生，但执行记忆（run_memory）中没有相应记录；
                #     2. Reflection 引擎看不到这段历史，误判任务未完成；
                #     3. 触发不必要的重规划，导致同一副作用被重复调用。
                # - 此过滤仅限制 Planning 阶段的 tool-calling loop；
                #   系统提示词（_build_system_prompt）中依然包含全量授权工具，
                #   LLM 依然知道这些工具的存在，并可在执行步骤中规划调用它们。
                planning_safe_names = self.tool_hub.get_planning_safe_names()
                tools = [
                    schema
                    for schema in authorized_tools
                    if schema.get("function", {}).get("name") in planning_safe_names
                ]

                # 计算被 planning_safe 过滤掉的工具列表，用于日志可观测性
                filtered_out = [
                    schema.get("function", {}).get("name")
                    for schema in authorized_tools
                    if schema.get("function", {}).get("name") not in planning_safe_names
                ]
                logger.info(
                    f"{Fore.YELLOW}[规划引擎] planning_safe 过滤完成: "
                    f"授权={len(authorized_tools)} 个 → 规划可调用={len(tools)} 个 "
                    f"| 已屏蔽副作用工具({len(filtered_out)}个): {filtered_out}{Style.RESET_ALL}"
                )

            # 规划阶段工具调用通知回调（双职责）：
            #
            # 职责 1 - SSE 实时推送（若 stream_callback 存在）：
            #   规划 LLM 在生成 JSON 计划前，可能多次调用工具（search / http_request 等）；
            #   这些调用发生在推理层（inference.py）的 tool_calling_loop 内部，
            #   通过回调向前端推送事件，让用户可见规划进度，而不是长时间等待无反馈。
            #
            # 职责 2 - 写入 run_memory（若 run_memory 存在）：
            #   将规划阶段工具调用结果持久化到 AgentRunMemory（entry_type="plan_tool_call"）。
            #   这样 Reflection 的 build_messages_for_reflection() 通过
            #   `iteration <= current_iteration` 条件自然包含这些历史，消除信息盲区：
            #   - 避免 Reflection 因看不到规划阶段已执行的操作而误判任务失败；
            #   - 防止由此触发的多余重规划和副作用工具重复调用。
            #
            # 两者完全解耦：有其一即构建回调；两者都无则回调为 None（跳过注册）。
            planning_tool_callback = None
            if stream_callback is not None or run_memory is not None:
                from app.tools.builtin.message import send_agent_message

                async def _planning_tool_callback(
                    tool_name: str,
                    params: dict,
                    result: object,
                    success: bool,
                ) -> None:
                    """
                    规划阶段工具调用回调（内嵌闭包，捕获 stream_callback / run_memory / iteration）。

                    同时承担：
                    1. SSE 实时事件推送（stream_callback 不为 None 时）
                    2. run_memory 持久化写入（run_memory 不为 None 时）
                    """
                    # ── 1. SSE 实时推送 ─────────────────────────────────────────
                    if stream_callback is not None:
                        status_label = "✅ 完成" if success else "❌ 失败"
                        await send_agent_message(
                            stream_callback=stream_callback,
                            message_type="progress",
                            content=f"规划中调用工具: {tool_name} {status_label}",
                            progress={
                                "stage": "plan_tool_call",
                                "iteration": iteration,
                                "tool_name": tool_name,
                                "success": success,
                            },
                            extra_data={
                                "tool_name": tool_name,
                                "is_planning_phase": True,
                            },
                        )

                    # ── 2. 写入 run_memory（消除 Reflection 信息盲区）────────────
                    # 规划阶段工具调用结果写入记忆，使 Reflection 在评估任务时能完整
                    # 看到"规划阶段做了哪些信息搜集"，不再误判"什么都没做"。
                    # 使用独立的 entry_type="plan_tool_call" 区分执行阶段，但格式完全
                    # 对齐 OpenAI Function Calling 配对，LLM 理解无障碍。
                    if run_memory is not None:
                        # 提取 error_msg：result 若为 dict 尝试取 error 字段；否则 str 化
                        err_msg = ""
                        if not success:
                            if isinstance(result, dict):
                                err_msg = str(result.get("error") or result.get("message") or "")
                            else:
                                err_msg = str(result) if result else ""

                        run_memory.write_planning_tool_call(
                            iteration=iteration,
                            tool_name=tool_name,
                            tool_args=params or {},
                            tool_result=result,
                            success=success,
                            error_msg=err_msg,
                        )

                    logger.debug(
                        f"{Fore.CYAN}[规划引擎] 规划阶段工具回调已触发: "
                        f"tool={tool_name}, success={success} "
                        f"| SSE={'已推送' if stream_callback else '跳过'} "
                        f"| run_memory={'已写入' if run_memory else '跳过'}{Style.RESET_ALL}"
                    )

                planning_tool_callback = _planning_tool_callback
                logger.debug(
                    f"{Fore.CYAN}[规划引擎] 规划阶段工具回调已绑定 "
                    f"(iteration={iteration}, "
                    f"SSE={'开启' if stream_callback else '关闭'}, "
                    f"run_memory={'开启' if run_memory else '关闭'}){Style.RESET_ALL}"
                )

            config = InferenceConfig(
                model=agent.agent_config.planning_model,
                temperature=0.7,
                # 规划阶段需要稳定输出可解析 JSON，适当提高上限，降低被截断风险。
                max_tokens=3072,
                tools=tools,
                # 注入规划阶段工具调用回调，使前端可见规划期间的工具调用进度
                tool_call_callback=planning_tool_callback,
            )

            if run_memory is not None:
                system_prompt = self._build_system_prompt(agent, available_tools, available_skills)
                trigger_prompt = self._build_trigger_prompt(
                    context=context,
                    user_rejected_tools=context.get("user_rejected_tools", []) if context else [],
                )
                messages = run_memory.build_messages_for_planning(
                    system_prompt=system_prompt,
                    current_iteration=iteration,
                    trigger_prompt=trigger_prompt,
                )
                logger.info(
                    f"{Fore.GREEN}[规划引擎] 使用 AgentRunMemory messages 模式，"
                    f"共 {len(messages)} 条消息（含历史记忆），iteration={iteration}{Style.RESET_ALL}"
                )
            else:
                prompt = self._build_planning_prompt(
                    agent=agent,
                    task=task,
                    available_tools=available_tools,
                    available_skills=available_skills,
                    context=context,
                    error_context=error_context,
                    reflection_history=reflection_history,
                )
                messages = [{"role": "user", "content": prompt}]
                logger.info(
                    f"{Fore.YELLOW}[规划引擎] 使用旧版文字拼接模式（未传入 run_memory）{Style.RESET_ALL}"
                )

            logger.info(
                f"{Fore.BLUE}[规划引擎] 正在调用 LLM 生成计划 "
                f"(模型={agent.agent_config.planning_model}, messages条数={len(messages)}){Style.RESET_ALL}"
            )
            response = await self.llm_hub.infer(messages=messages, config=config)

            logger.info(f"{Fore.GREEN}[规划引擎] LLM 返回原始规划内容:{Style.RESET_ALL}")
            logger.info(f"{Fore.GREEN}{response.content[:800] if response.content else '（空响应）'}{Style.RESET_ALL}")

            plan = self._parse_plan(response.content)
            # 若模型输出被截断（finish_reason=length）且 JSON 解析失败，
            # 自动触发一次“短计划重试”，避免直接退化为 final_answer 错误分支。
            if self._should_retry_plan_due_to_truncation(plan, response):
                logger.warning(
                    f"{Fore.YELLOW}[规划引擎] 检测到规划输出被截断且 JSON 解析失败，"
                    f"将自动重试并强制模型输出短 JSON 计划。{Style.RESET_ALL}"
                )
                retry_plan = await self._retry_plan_after_truncation(
                    agent=agent,
                    messages=messages,
                    tools=tools,
                )
                # 仅当重试解析成功时替换原计划，避免覆盖原始兜底结果。
                if not self._is_json_parse_failed_plan(retry_plan):
                    plan = retry_plan
            elif self._is_json_parse_failed_plan(plan):
                logger.warning(
                    f"{Fore.YELLOW}[规划引擎] 检测到非截断型 JSON 解析失败，"
                    f"将自动触发一次 JSON 修复重试。{Style.RESET_ALL}"
                )
                retry_plan = await self._retry_plan_after_invalid_json(
                    agent=agent,
                    messages=messages,
                    raw_output=response.content or "",
                )
                if not self._is_json_parse_failed_plan(retry_plan):
                    plan = retry_plan

            plan = self._validate_plan_capabilities(
                agent=agent,
                plan=plan,
                available_tools=available_tools,
                available_skills=available_skills,
            )

            logger.info(f"{Fore.GREEN}计划创建成功，共 {len(plan.steps)} 个步骤{Style.RESET_ALL}")
            return plan

        except Exception as exc:
            logger.error(f"{Fore.RED}创建计划失败: {exc}{Style.RESET_ALL}")
            return Plan(
                steps=[
                    PlanStep(
                        action="final_answer",
                        content=f"抱歉，我无法为任务 '{task}' 创建执行计划。错误: {str(exc)}",
                    )
                ],
                reasoning="规划失败，返回错误信息",
            )

    def _build_system_prompt(
        self,
        agent: Agent,
        available_tools: List[Tool],
        available_skills: List[Skill],
    ) -> str:
        """
        构建规划的系统提示词（system role）

        包含 Agent 角色定义、可用工具/技能/子Agent 清单以及 JSON 输出格式要求。
        这部分内容固定不变，适合放在 system 消息中。
        其余的历史上下文（错误记录、反思历史）通过 AgentRunMemory 注入 messages 数组，
        而不是文字拼接到这里——这样 LLM 能以「真实对话」而非「描述文本」理解历史。
        """
        return self.prompt_manager.render_prompt(
            "system_role_and_constraints",
            agent_name=agent.name,
            agent_description=agent.description,
            agent_role=agent.role,
            tools_text=self._format_tools(available_tools),
            skills_text=self._format_skills(available_skills),
            child_agents_text=", ".join(agent.child_agents) if agent.child_agents else "无",
        )

    def _build_trigger_prompt(
        self,
        context: Optional[Dict[str, Any]] = None,
        user_rejected_tools: Optional[List[str]] = None,
    ) -> str:
        """构建 run_memory 模式下的触发提示词。"""
        rejected = user_rejected_tools or []
        return self.prompt_manager.render_prompt(
            "iteration_trigger_with_rejections",
            rejected_tools_text=", ".join(rejected),
            file_write_rejected=("file_write" in rejected),
        )

    def _build_planning_prompt(
        self,
        agent: Agent,
        task: str,
        available_tools: List[Tool],
        available_skills: List[Skill],
        context: Optional[Dict[str, Any]] = None,
        error_context: Optional[List[Dict[str, Any]]] = None,
        reflection_history: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        构建兼容旧链路的文字拼接规划提示词。
        构建规划 Prompt

        Args:
            agent: Agent 实例
            task: 任务描述
            available_tools: 可用工具列表
            available_skills: 可用技能列表
            context: 额外上下文
            error_context: 上一轮失败的步骤错误信息
            reflection_history: 历次迭代的反思结论（累积列表）

        Returns:
            str: Prompt 文本

        """
        logger.debug(f"{Fore.CYAN}构建规划 Prompt{Style.RESET_ALL}")

        prompt = self.prompt_manager.render_prompt(
            "legacy_planning_with_task",
            agent_name=agent.name,
            agent_description=agent.description,
            agent_role=agent.role,
            task=task,
            tools_text=self._format_tools(available_tools),
            skills_text=self._format_skills(available_skills),
            child_agents_text=", ".join(agent.child_agents) if agent.child_agents else "无",
        )

        if context:
            def _compact(value: Any, max_len: int = 5000) -> str:
                try:
                    text = json.dumps(value, ensure_ascii=False, indent=2)
                except Exception:
                    text = str(value)
                if len(text) > max_len:
                    text = text[:max_len] + "\n...（上下文已截断）"
                return text

            context_block = _compact(context, max_len=5000)
            prompt += f"""

# 🧠 跨迭代执行上下文（请重点参考）
以下是上一轮（或最近轮次）的计划、执行结果与总结：
{context_block}

【重规划强约束】
- 若上下文中已包含完成任务所需的关键数据（如已查到订单总金额），优先直接复用，不要重复查询相同信息。
- 若 user_rejected_tools 显示某工具已被用户拒绝，不要再次规划该工具；应提供替代方案或在 final_answer 中明确告知受限原因。
- 新计划应尽量减少重复步骤，明确说明为何需要新增步骤。
"""

        if context and "file_write" in context.get("user_rejected_tools", []):
            prompt += """
【强约束：文件写入能力已被降级】
- **当用户已拒绝 file_write 且需求是保存内容到文件时**：若你有 python_executor 可用，应规划一步「用代码生成能力帮用户完成意图」——**生成并 print 出一段完整的、用户可在本机运行的 Python 脚本**，脚本内容为：将本应写入的数据写入本地文件（如 open(...).write(...)）。这样工具 output 即为该脚本源码，最终回答会完整交付脚本并说明「请将下方代码保存为 .py 文件后运行即可在本地生成文件」。仅当确实无可行方案时再告知无法完成。
"""

        if error_context:
            error_lines = []
            for idx, err in enumerate(error_context, 1):
                step_desc = err.get("step_desc", "未知步骤")
                error_msg = err.get("error_msg", "")
                error_type = err.get("error_type", "")
                suggestion = err.get("suggestion", "")
                line = f"{idx}. [{error_type}] {step_desc}: {error_msg}"
                if suggestion:
                    line += f" → 建议: {suggestion}"
                error_lines.append(line)
            error_block = "\n".join(error_lines)
            prompt += f"""

# ⚠️ 上一轮执行发现以下错误，请在新计划中规避（不要重复同样的失败步骤）：
{error_block}

请根据以上错误信息，调整执行策略，确保新计划能够避开已知问题。
请只返回 JSON，不要包含其他文本。"""
            logger.info(
                f"{Fore.YELLOW}[规划引擎] 已将 {len(error_context)} 条错误信息注入规划 Prompt{Style.RESET_ALL}"
            )

        if reflection_history:
            history_lines = []
            for hist in reflection_history:
                iteration_num = hist.get("iteration", "?") + 1
                success = hist.get("success", False)
                feedback = hist.get("feedback", "")
                summary = hist.get("summary", "")
                status_str = "成功" if success else "失败"
                line = (
                    f"第 {iteration_num} 轮 [{status_str}] 反馈: {feedback}"
                    + (f" | 总结: {summary}" if summary else "")
                )
                history_lines.append(line)
            history_block = "\n".join(history_lines)

            if agent.child_agents:
                available_agents_text = f"\n【可用智能体】: {', '.join(agent.child_agents)}"
            else:
                available_agents_text = (
                    "\n【提示】如果当前 Agent 无法完成该任务（如需要数据库访问权限），"
                    "请在最终回答中建议用户返回主智能体（客服）寻求帮助"
                )

            prompt += f"""

# 📜 历史迭代反思记录
以下是本任务之前各轮次的执行结果和反思结论，请仔细参考，避免重复无效策略：
{history_block}

【重要指引】
- 如果历史记录显示之前的策略均无效，请尝试完全不同的方法或工具组合
- 如果经过多轮尝试后仍然无法完成任务（例如因权限不足、工具缺失、能力边界等），
  请在 final_answer 中诚实告知用户「当前 Agent 无法完成该任务」并解释原因{available_agents_text}
- 不要重复已经失败的相同策略
请只返回 JSON，不要包含其他文本。"""
            logger.info(
                f"{Fore.YELLOW}[规划引擎] 已将 {len(reflection_history)} 条历史反思注入规划 Prompt，"
                f"引导 LLM 改进策略{Style.RESET_ALL}"
            )

        return prompt

    def _format_tools(self, tools: List[Tool]) -> str:
        """格式化工具列表。"""
        if not tools:
            return "无可用工具"
        return "\n".join([f"- {tool.name}: {tool.schema.description}" for tool in tools])

    def _format_skills(self, skills: List[Skill]) -> str:
        """
        格式化技能列表。

        设计说明：
        - 规划阶段是模型“选技能”的关键入口，若只给描述而不暴露输入参数名，
          模型容易把参数名写错（例如把 weather 的 location 写成 city）。
        - 这里显式注入每个技能的输入参数与简短说明，降低规划参数漂移概率。
        """
        if not skills:
            return "无可用技能"

        lines: List[str] = []
        for skill in skills:
            base = f"- {skill.skill_id} ({skill.name}): {skill.description}"

            # 轻量化参数展示：优先使用 param_schemas（由 metadata 解析而来）
            param_schemas = getattr(skill, "param_schemas", {}) or {}
            if param_schemas:
                param_parts: List[str] = []
                for param_name, schema in param_schemas.items():
                    desc = ""
                    try:
                        desc = (getattr(schema, "description", "") or "").strip()
                    except Exception:
                        desc = ""

                    # 说明为空时仅展示参数名，避免噪音
                    if desc:
                        param_parts.append(f"{param_name}({desc})")
                    else:
                        param_parts.append(str(param_name))

                # 控制长度，避免规划 Prompt 过长
                preview = ", ".join(param_parts[:8])
                if len(param_parts) > 8:
                    preview += ", ..."
                base += f" | 输入参数: {preview}"
            else:
                base += " | 输入参数: 无"

            lines.append(base)

        return "\n".join(lines)

    def _validate_plan_capabilities(
        self,
        *,
        agent: Agent,
        plan: Plan,
        available_tools: List[Tool],
        available_skills: List[Skill],
    ) -> Plan:
        """
        对规划结果做能力边界校验与轻量标准化。

        设计原因：
        - 即使 Prompt 只暴露了授权工具/技能，LLM 仍可能在 JSON 中编造未授权能力；
        - 若不在规划公共层阻断，错误会延迟到执行阶段才暴露，浪费一整轮执行/反思；
        - 因此这里统一收口，保证“计划产物”本身就满足当前 Agent 的权限边界。
        """
        allowed_actions = {"tool", "skill", "delegate", "final_answer"}
        allowed_tool_names = {
            str(tool.name).strip()
            for tool in (available_tools or [])
            if str(getattr(tool, "name", "")).strip()
        }
        allowed_skill_ids = {
            str(skill.skill_id).strip()
            for skill in (available_skills or [])
            if str(getattr(skill, "skill_id", "")).strip()
        }
        allowed_agent_ids = {
            str(agent_id).strip()
            for agent_id in (agent.child_agents or [])
            if isinstance(agent_id, str) and str(agent_id).strip()
        }

        normalized_steps: List[PlanStep] = []
        invalid_reasons: List[str] = []

        for index, step in enumerate(plan.steps, start=1):
            action = str(step.action or "").strip()
            params = dict(step.params or {})

            # 兼容旧输出：若工具名被直接写成 action，则标准化为 action="tool"。
            if action not in allowed_actions and action in allowed_tool_names:
                logger.warning(
                    f"{Fore.YELLOW}[规划引擎] 检测到工具名被误写为 action，"
                    f"已自动标准化: {action}{Style.RESET_ALL}"
                )
                params.setdefault("tool_name", action)
                action = "tool"

            action, params = self._normalize_capability_reference_drift(
                index=index,
                action=action,
                params=params,
                allowed_tool_names=allowed_tool_names,
                allowed_skill_ids=allowed_skill_ids,
            )

            if action not in allowed_actions:
                invalid_reasons.append(f"第{index}步 action='{action}' 不受支持")
                continue

            if action == "tool":
                tool_name = str(params.get("tool_name", "") or "").strip()
                if not tool_name:
                    invalid_reasons.append(f"第{index}步缺少 tool_name")
                    continue
                if tool_name not in allowed_tool_names:
                    invalid_reasons.append(
                        f"第{index}步工具 '{tool_name}' 不在当前 Agent 授权范围内"
                    )
                    continue
                params = self._normalize_step_args_payload(
                    action="tool",
                    params=params,
                )

            elif action == "skill":
                skill_id = str(params.get("skill_id", "") or "").strip()
                if not skill_id:
                    invalid_reasons.append(f"第{index}步缺少 skill_id")
                    continue
                if skill_id not in allowed_skill_ids:
                    invalid_reasons.append(
                        f"第{index}步技能 '{skill_id}' 当前不可用"
                    )
                    continue
                params = self._normalize_step_args_payload(
                    action="skill",
                    params=params,
                )

            elif action == "delegate":
                agent_id = str(params.get("agent_id", "") or "").strip()
                if not agent_id:
                    invalid_reasons.append(f"第{index}步缺少 agent_id")
                    continue
                if agent_id not in allowed_agent_ids:
                    invalid_reasons.append(
                        f"第{index}步子 Agent '{agent_id}' 不在当前可委派列表中"
                    )
                    continue

            normalized_steps.append(PlanStep(action=action, **params))

        if invalid_reasons:
            logger.warning(
                f"{Fore.YELLOW}[规划引擎] 计划校验失败，将阻断无效计划执行 | "
                f"agent={agent.name} | reasons={invalid_reasons}{Style.RESET_ALL}"
            )
            return Plan(
                steps=[
                    PlanStep(
                        action="final_answer",
                        content=(
                            "当前规划结果不合法，需要重新规划。原因："
                            + "；".join(invalid_reasons)
                            + "。如需使用受限能力，请改为委派给具备对应权限的子 Agent。"
                        ),
                    )
                ],
                reasoning="计划校验失败",
            )

        return Plan(steps=normalized_steps, reasoning=plan.reasoning)

    def _normalize_capability_reference_drift(
        self,
        *,
        index: int,
        action: str,
        params: Dict[str, Any],
        allowed_tool_names: set[str],
        allowed_skill_ids: set[str],
    ) -> tuple[str, Dict[str, Any]]:
        """
        归一化规划步骤里的能力类型/标识字段漂移。

        设计原因：
        - 线上已观测到模型把“工具”误写成“技能”，例如把 `skill_install`
          写成 `{"action":"skill","skill_id":"skill_install"}`；
        - 这类问题本质上属于规划公共层的结构漂移，而不是某个具体能力缺失；
        - 因此这里统一做“框架级归一化”，避免误把“可用工具”判成“当前不可用”。
        """
        normalized_action = str(action or "").strip()
        normalized_params = dict(params or {})

        def _read_text(key: str) -> str:
            return str(normalized_params.get(key, "") or "").strip()

        def _read_nested_params() -> Dict[str, Any]:
            nested = normalized_params.get("params")
            return dict(nested) if isinstance(nested, dict) else {}

        def _extract_install_source() -> tuple[str, Optional[str]]:
            """
            提取“安装来源”字段，兼容模型把安装工具参数写成 source/reference 等别名。

            设计原因：
            - 在“安装某个外部 skill 包”任务里，模型常把目标 skill 本身写成
              `action="skill"`，同时把真实安装引用放进 `source` / `reference`；
            - 此时若直接按“调用 skill”处理，就会把“待安装目标”误判成“当前不可用技能”；
            - 因而这里需要在规划公共层识别“安装意图”并转交给结构化工具 `skill_install`。
            """
            candidate_keys = (
                "package",
                "source",
                "reference",
                "package_ref",
                "package_source",
                "install_ref",
                "skill_reference",
                "install_source",
                "ref",
                "uri",
                "url",
                "repo",
                "command",
            )
            nested_params = _read_nested_params()
            for key in candidate_keys:
                top_level_value = str(normalized_params.get(key, "") or "").strip()
                if top_level_value:
                    return top_level_value, key
                nested_value = str(nested_params.get(key, "") or "").strip()
                if nested_value:
                    return nested_value, f"params.{key}"
            return "", None

        def _rewrite_identifier(
            *,
            target_action: str,
            identifier_key: str,
            identifier_value: str,
            source_key: str,
            reason: str,
        ) -> None:
            nonlocal normalized_action
            logger.warning(
                f"{Fore.YELLOW}[规划引擎] 检测到能力引用漂移，已在公共规划层自动归一化 | "
                f"step={index} | from_action={action} | to_action={target_action} | "
                f"source_key={source_key} | target_key={identifier_key} | "
                f"value={identifier_value} | reason={reason}{Style.RESET_ALL}"
            )
            normalized_action = target_action
            normalized_params.pop("tool_name", None)
            normalized_params.pop("skill_id", None)
            normalized_params[identifier_key] = identifier_value

        tool_name = _read_text("tool_name")
        skill_id = _read_text("skill_id")

        # 先处理“字段名写错，但能力类型没错”的场景。
        if normalized_action == "tool":
            if (not tool_name or tool_name not in allowed_tool_names) and skill_id in allowed_tool_names:
                _rewrite_identifier(
                    target_action="tool",
                    identifier_key="tool_name",
                    identifier_value=skill_id,
                    source_key="skill_id",
                    reason="工具步骤把 tool_name 误写成了 skill_id",
                )
                tool_name = skill_id
                skill_id = ""
        elif normalized_action == "skill":
            if (not skill_id or skill_id not in allowed_skill_ids) and tool_name in allowed_skill_ids:
                _rewrite_identifier(
                    target_action="skill",
                    identifier_key="skill_id",
                    identifier_value=tool_name,
                    source_key="tool_name",
                    reason="技能步骤把 skill_id 误写成了 tool_name",
                )
                skill_id = tool_name
                tool_name = ""

        # 再处理“工具/技能能力类型被写反”的公共漂移。
        if normalized_action == "tool":
            tool_name = _read_text("tool_name")
            if tool_name and tool_name not in allowed_tool_names and tool_name in allowed_skill_ids:
                _rewrite_identifier(
                    target_action="skill",
                    identifier_key="skill_id",
                    identifier_value=tool_name,
                    source_key="tool_name",
                    reason="模型把技能误规划为了工具",
                )
            elif not tool_name and skill_id in allowed_skill_ids:
                _rewrite_identifier(
                    target_action="skill",
                    identifier_key="skill_id",
                    identifier_value=skill_id,
                    source_key="skill_id",
                    reason="模型把技能误规划为了工具，且标识落在 skill_id 字段",
                )
        elif normalized_action == "skill":
            skill_id = _read_text("skill_id")
            if skill_id and skill_id not in allowed_skill_ids and skill_id in allowed_tool_names:
                _rewrite_identifier(
                    target_action="tool",
                    identifier_key="tool_name",
                    identifier_value=skill_id,
                    source_key="skill_id",
                    reason="模型把工具误规划为了技能",
                )
            elif not skill_id and tool_name in allowed_tool_names:
                _rewrite_identifier(
                    target_action="tool",
                    identifier_key="tool_name",
                    identifier_value=tool_name,
                    source_key="tool_name",
                    reason="模型把工具误规划为了技能，且标识落在 tool_name 字段",
                )

        # 对“安装目标被误写成 skill 调用”的场景做框架级纠偏：
        # 若当前 Agent 具备 `skill_install` 工具，且模型把待安装 skill 的真实来源
        # 写进了 source/reference/package 等字段，则应改写为结构化安装工具调用，
        # 而不是把目标 skill 当成“当前已可执行的技能”去校验。
        if normalized_action == "skill":
            skill_id = _read_text("skill_id")
            install_source, install_source_key = _extract_install_source()
            if (
                skill_id
                and skill_id not in allowed_skill_ids
                and "skill_install" in allowed_tool_names
                and install_source
            ):
                nested_params = _read_nested_params()
                nested_params.setdefault("package", install_source)
                nested_params.setdefault("skill_name", skill_id)
                logger.warning(
                    f"{Fore.YELLOW}[规划引擎] 检测到“待安装目标 skill”被误规划为技能调用，"
                    f"已在公共规划层自动改写为 skill_install 工具 | "
                    f"step={index} | skill_id={skill_id} | "
                    f"install_source_key={install_source_key} | install_source={install_source}"
                    f"{Style.RESET_ALL}"
                )
                normalized_action = "tool"
                normalized_params = {
                    "tool_name": "skill_install",
                    "params": nested_params,
                }

        return normalized_action, normalized_params

    def _normalize_step_args_payload(
        self,
        *,
        action: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        规范化步骤参数结构，兼容 LLM 输出的扁平参数写法。

        兼容场景：
        - 标准写法：{"action":"tool","tool_name":"x","params":{"a":1}}
        - 脏写法：{"action":"tool","tool_name":"x","a":1}
        - 直接工具 action 被标准化后：{"action":"send_message","content":"..."}

        统一收口后，执行层总能读到 `step.params["params"]`。
        """
        normalized = dict(params or {})
        control_keys_map = {
            "tool": {"tool_name"},
            "skill": {"skill_id"},
        }
        control_keys = control_keys_map.get(action)
        if not control_keys:
            return normalized

        nested_params = normalized.get("params")
        merged_params = dict(nested_params) if isinstance(nested_params, dict) else {}
        for key, value in list(normalized.items()):
            if key in control_keys or key == "params":
                continue
            merged_params.setdefault(key, value)

        normalized["params"] = merged_params
        for key in list(normalized.keys()):
            if key in control_keys or key == "params":
                continue
            normalized.pop(key, None)
        return normalized

    def _parse_plan(self, llm_output: str) -> Plan:
        """解析 LLM 返回的计划。"""
        logger.debug(f"{Fore.CYAN}解析 LLM 输出为计划{Style.RESET_ALL}")

        try:
            llm_output = (llm_output or "").strip()
            plan_dict = self._extract_plan_dict(llm_output)

            steps: List[PlanStep] = []
            for step_dict in plan_dict.get("steps", []):
                action = step_dict.pop("action")
                steps.append(PlanStep(action=action, **step_dict))

            reasoning = plan_dict.get("reasoning", "")
            logger.info(f"{Fore.GREEN}计划解析成功，共 {len(steps)} 个步骤{Style.RESET_ALL}")
            return Plan(steps=steps, reasoning=reasoning)

        except json.JSONDecodeError as exc:
            logger.error(f"{Fore.RED}JSON 解析失败: {exc}{Style.RESET_ALL}")
            logger.error(f"{Fore.RED}LLM 输出: {llm_output[:200]}...{Style.RESET_ALL}")
            return Plan(
                steps=[
                    PlanStep(
                        action="final_answer",
                        content="解析计划失败，LLM 返回的不是有效的 JSON 格式",
                    )
                ],
                reasoning="JSON 解析失败",
            )

        except Exception as exc:
            logger.error(f"{Fore.RED}解析计划时发生错误: {exc}{Style.RESET_ALL}")
            return Plan(
                steps=[
                    PlanStep(
                        action="final_answer",
                        content=f"解析计划时发生错误: {str(exc)}",
                    )
                ],
                reasoning="解析错误",
            )

    def _extract_plan_dict(self, llm_output: str) -> Dict[str, Any]:
        """
        从混合格式 LLM 输出中恢复计划字典。

        兼容场景：
        1. 标准 JSON 对象：`{"steps":[...],"reasoning":"..."}`
        2. 顶层 JSON 数组：`[{"action":"tool", ...}]`
        3. `<think>...</think>` + 半结构化文本：
           `推理过程: ...`
           `执行步骤: [{"action":"tool", ...}]`
        """
        payload = extract_json_payload(llm_output)
        try:
            parsed = self._load_json_like_payload(payload)
        except json.JSONDecodeError:
            semi_structured_plan = self._extract_semistructured_plan(llm_output)
            if semi_structured_plan:
                return semi_structured_plan
            raise

        if isinstance(parsed, dict) and isinstance(parsed.get("steps"), list):
            return parsed

        if isinstance(parsed, list):
            return {
                "steps": parsed,
                "reasoning": self._extract_plan_reasoning(llm_output),
            }

        semi_structured_plan = self._extract_semistructured_plan(llm_output)
        if semi_structured_plan:
            return semi_structured_plan

        raise json.JSONDecodeError("规划输出中未找到可执行的 steps 数组", llm_output, 0)

    def _load_json_like_payload(self, payload: str) -> Any:
        """
        尽量把“接近 JSON”的文本恢复为结构化对象。

        公共修复目标：
        1. 兼容尾逗号、Python 字面量 dict/list 等轻度格式漂移；
        2. 避免规划层因为微小格式问题直接退化到“JSON 解析失败”；
        3. 保持为公共解析能力，而不是针对某个模型输出做特判。
        """
        text = (payload or "").strip()
        if not text:
            raise json.JSONDecodeError("空规划输出", payload or "", 0)

        try:
            return json.loads(text)
        except json.JSONDecodeError as original_exc:
            # 兜底 1：去掉常见的 JSON 尾逗号
            trailing_comma_fixed = re.sub(r",(\s*[}\]])", r"\1", text)
            if trailing_comma_fixed != text:
                try:
                    return json.loads(trailing_comma_fixed)
                except json.JSONDecodeError:
                    pass

            # 兜底 2：兼容 Python 风格字面量（单引号 / True / False / None）
            literal_parsed = self._try_literal_eval_payload(text)
            if literal_parsed is not None:
                return literal_parsed

            raise original_exc

    def _try_literal_eval_payload(self, payload: str) -> Optional[Any]:
        """
        尝试使用 Python 字面量语法恢复结构化载荷。

        说明：
        - 某些模型会输出 `{'steps': [...], 'reasoning': '...'}` 这类 Python dict；
        - 对规划层来说，这仍属于“结构完整，只是语法轻度漂移”；
        - 这里统一在公共解析层兜底，减少无意义重规划。
        """
        try:
            parsed = ast.literal_eval(payload)
        except (ValueError, SyntaxError):
            return None
        return parsed if isinstance(parsed, (dict, list)) else None

    def _extract_semistructured_plan(self, llm_output: str) -> Optional[Dict[str, Any]]:
        """
        兼容“说明文字 + 执行步骤数组”的半结构化规划文本。

        典型示例：
        `【规划-第1轮】`
        `推理过程: ...`
        `执行步骤: [{"action":"tool", ...}]`
        """
        text = strip_think_blocks(llm_output or "")
        if not text:
            return None

        step_label_match = re.search(r"执行步骤\s*[:：]", text)
        if not step_label_match:
            return None

        remaining = text[step_label_match.end() :].strip()
        step_payload = (
            extract_first_balanced_json_array(remaining)
            or extract_first_balanced_json_object(remaining)
        )
        if not step_payload:
            return None

        parsed_steps = json.loads(step_payload)
        if isinstance(parsed_steps, dict):
            plan_dict = dict(parsed_steps)
            if not isinstance(plan_dict.get("steps"), list):
                return None
        elif isinstance(parsed_steps, list):
            plan_dict = {"steps": parsed_steps}
        else:
            return None

        reasoning = self._extract_plan_reasoning(text)
        if reasoning and not plan_dict.get("reasoning"):
            plan_dict["reasoning"] = reasoning

        return plan_dict

    def _extract_plan_reasoning(self, llm_output: str) -> str:
        """从半结构化文本中提取“推理过程”字段。"""
        text = strip_think_blocks(llm_output or "")
        if not text:
            return ""

        match = re.search(
            r"推理过程\s*[:：]\s*([\s\S]*?)(?=\n\s*(?:执行步骤|计划内容)\s*[:：]|\Z)",
            text,
        )
        if not match:
            return ""
        return match.group(1).strip()

    def _is_json_parse_failed_plan(self, plan: Plan) -> bool:
        """
        判断计划是否属于“JSON 解析失败兜底计划”。

        说明：
        - _parse_plan 解析失败时会返回固定兜底格式：
          单步 final_answer + reasoning='JSON 解析失败'。
        - 这里集中封装判断逻辑，便于 create_plan 里做重试决策。
        """
        if not isinstance(plan, Plan):
            return False
        if plan.reasoning != "JSON 解析失败":
            return False
        if len(plan.steps) != 1:
            return False
        step = plan.steps[0]
        if step.action != "final_answer":
            return False
        content = str(step.params.get("content", ""))
        return "解析计划失败" in content

    def _should_retry_plan_due_to_truncation(self, plan: Plan, response: Any) -> bool:
        """
        判断是否需要触发“截断重试”。

        触发条件：
        1. 当前计划是 JSON 解析失败兜底；
        2. 模型 finish_reason 明确为 length（输出被截断）。
        """
        finish_reason = str(getattr(response, "finish_reason", "") or "").lower()
        return self._is_json_parse_failed_plan(plan) and finish_reason == "length"

    async def _retry_plan_after_truncation(
        self,
        agent: Agent,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> Plan:
        """
        在首次规划输出被截断时，追加“短 JSON 计划”约束并重试一次。

        设计目标：
        - 防止模型在 params 中塞入超长代码/原始数据，导致 JSON 再次被截断；
        - 优先恢复可执行计划，减少进入反思-重规划死循环的概率。
        """
        try:
            from app.llm_hub.inference import InferenceConfig

            retry_prompt = self.prompt_manager.render_prompt("retry_after_length")
            retry_messages = list(messages) + [{"role": "user", "content": retry_prompt}]
            retry_config = InferenceConfig(
                model=agent.agent_config.planning_model,
                temperature=0.2,
                # 重试阶段主打“短输出+可解析”，输出上限适中即可。
                max_tokens=1536,
                tools=tools,
            )
            logger.info(
                f"{Fore.BLUE}[规划引擎] 触发截断重试：追加短计划约束，"
                f"messages条数={len(retry_messages)}{Style.RESET_ALL}"
            )
            retry_response = await self.llm_hub.infer(messages=retry_messages, config=retry_config)
            logger.info(
                f"{Fore.GREEN}[规划引擎] 截断重试返回内容预览:"
                f"{Style.RESET_ALL}"
            )
            logger.info(
                f"{Fore.GREEN}"
                f"{retry_response.content[:800] if retry_response.content else '（空响应）'}"
                f"{Style.RESET_ALL}"
            )

            retry_plan = self._parse_plan(retry_response.content)
            if self._is_json_parse_failed_plan(retry_plan):
                logger.error(
                    f"{Fore.RED}[规划引擎] 截断重试后仍为 JSON 解析失败，"
                    f"保留兜底计划。{Style.RESET_ALL}"
                )
            else:
                logger.info(
                    f"{Fore.GREEN}[规划引擎] 截断重试成功，解析到 {len(retry_plan.steps)} 个步骤。"
                    f"{Style.RESET_ALL}"
                )
            return retry_plan
        except Exception as exc:
            logger.error(
                f"{Fore.RED}[规划引擎] 截断重试发生异常: {exc}"
                f"{Style.RESET_ALL}"
            )
            return Plan(
                steps=[
                    PlanStep(
                        action="final_answer",
                        content="解析计划失败，且重试生成短计划时发生异常",
                    )
                ],
                reasoning="JSON 解析失败",
            )

    async def _retry_plan_after_invalid_json(
        self,
        agent: Agent,
        messages: List[Dict[str, Any]],
        raw_output: str,
    ) -> Plan:
        """
        当规划输出不是有效 JSON，但看起来并非“长度截断”时，触发一次结构修复重试。

        设计目标：
        - 将“轻度跑偏的格式问题”收口在规划公共层，不让它污染执行/反思主链路；
        - 让模型专注做“JSON 修复”，而不是重新自由发挥整轮规划；
        - 避免中间轨迹出现“解析计划失败”的假 final_answer 噪声。
        """
        try:
            from app.llm_hub.inference import InferenceConfig

            repair_prompt = self.prompt_manager.render_prompt(
                "repair_after_invalid_json",
                raw_output=raw_output[:12000],
            )
            retry_messages = list(messages) + [{"role": "user", "content": repair_prompt}]
            retry_config = InferenceConfig(
                model=agent.agent_config.planning_model,
                temperature=0.1,
                max_tokens=1536,
                tools=[],
            )
            logger.info(
                f"{Fore.BLUE}[规划引擎] 触发 JSON 修复重试："
                f"messages条数={len(retry_messages)}{Style.RESET_ALL}"
            )
            retry_response = await self.llm_hub.infer(messages=retry_messages, config=retry_config)
            logger.info(f"{Fore.GREEN}[规划引擎] JSON 修复重试返回内容预览:{Style.RESET_ALL}")
            logger.info(
                f"{Fore.GREEN}"
                f"{retry_response.content[:800] if retry_response.content else '（空响应）'}"
                f"{Style.RESET_ALL}"
            )

            retry_plan = self._parse_plan(retry_response.content)
            if self._is_json_parse_failed_plan(retry_plan):
                logger.error(
                    f"{Fore.RED}[规划引擎] JSON 修复重试后仍未恢复有效计划，"
                    f"保留原兜底结果。{Style.RESET_ALL}"
                )
            else:
                logger.info(
                    f"{Fore.GREEN}[规划引擎] JSON 修复重试成功，解析到 {len(retry_plan.steps)} 个步骤。"
                    f"{Style.RESET_ALL}"
                )
            return retry_plan
        except Exception as exc:
            logger.error(
                f"{Fore.RED}[规划引擎] JSON 修复重试发生异常: {exc}{Style.RESET_ALL}"
            )
            return Plan(
                steps=[
                    PlanStep(
                        action="final_answer",
                        content="解析计划失败，且 JSON 修复重试时发生异常",
                    )
                ],
                reasoning="JSON 解析失败",
            )


if __name__ == "__main__":
    print(f"\n{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Planning Engine 测试{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}\n")

    step = PlanStep(action="tool", tool_name="search", params={"query": "test"})
    print(f"创建计划步骤: {step.to_dict()}")

    plan = Plan(steps=[step], reasoning="这是一个测试计划")
    print(f"创建计划: {plan.to_dict()}")

    print(f"\n{Fore.GREEN}测试完成!{Style.RESET_ALL}\n")
