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
更新时间: 2026-03-06（集成 AgentRunMemory 记忆系统）
"""

import json
from typing import Dict, List, Any, Optional, TYPE_CHECKING
from loguru import logger
from colorama import Fore, Style

from app.agents.base import Agent
from app.tools.base import Tool
from app.skills.base import Skill

# NOTE: 使用 TYPE_CHECKING 避免循环导入；运行时通过函数参数类型注解字符串引用
if TYPE_CHECKING:
    from app.memory.agent_run_memory import AgentRunMemory


class PlanStep:
    """计划步骤"""
    
    def __init__(
        self,
        action: str,
        **kwargs
    ):
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
            **self.params
        }


class Plan:
    """执行计划"""
    
    def __init__(
        self,
        steps: List[PlanStep],
        reasoning: str = ""
    ):
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
            "reasoning": self.reasoning
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
        iteration: int = 0
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
        logger.info(
            f"{Fore.BLUE}开始为 Agent '{agent.name}' 创建执行计划{Style.RESET_ALL}"
        )
        # todo 一会解开注释
        # logger.info(f"{Fore.CYAN}任务: {task}{Style.RESET_ALL}")

        # 构建规划 Prompt（重规划时携带错误上下文和历史反思，提升修正质量）
        if error_context:
            logger.info(
                f"{Fore.YELLOW}[规划引擎] 本次为错误感知重规划，携带 {len(error_context)} 条错误记录{Style.RESET_ALL}"
            )
        if reflection_history:
            logger.info(
                f"{Fore.YELLOW}[规划引擎] 本次携带 {len(reflection_history)} 条历史反思记录，引导改进规划方向{Style.RESET_ALL}"
            )
        # 使用 LLM 生成计划
        logger.info(f"{Fore.BLUE}调用 LLM 生成计划...{Style.RESET_ALL}")
        
        try:
            from app.llm_hub.inference import InferenceConfig
            
            # NOTE: 只向 LLM 提供该 Agent 实际有权限使用的工具定义。
            # 禁止使用全量 tool_hub.get_schemas()，否则 LLM 会看到被禁止的工具（如 database_query）
            # 并在计划中反复规划调用它，导致无限迭代直到达到最大次数。
            tools = []
            if self.tool_hub and available_tools:
                allowed_tool_names = {t.name for t in available_tools}
                all_schemas = self.tool_hub.get_schemas()
                tools = [
                    s for s in all_schemas
                    if s.get("function", {}).get("name") in allowed_tool_names
                ]
                logger.debug(
                    f"{Fore.CYAN}[规划引擎] 工具定义已过滤: "
                    f"授权 {len(tools)}/{len(all_schemas)} 个（过滤掉了未授权工具）{Style.RESET_ALL}"
                )
            
            config = InferenceConfig(
                model=agent.agent_config.planning_model,
                temperature=0.7,
                max_tokens=2048,
                tools=tools
            )

            # ── 核心改造：优先使用 run_memory messages 格式传递历史记忆 ────────
            # 当 run_memory 存在时，通过 build_messages_for_planning() 生成完整的
            # messages 数组，历史的计划/工具调用/反思/用户操作等全部以标准 OpenAI
            # 消息格式呈现给 LLM，准确度远优于文字拼接方式。
            # 当 run_memory 不存在时（如子 Agent 首次调用等），降级为旧的 prompt 文字拼接。
            if run_memory is not None:
                system_prompt = self._build_system_prompt(
                    agent, available_tools, available_skills
                )
                trigger_prompt = self._build_trigger_prompt(
                    context=context,
                    user_rejected_tools=context.get("user_rejected_tools", []) if context else []
                )
                messages = run_memory.build_messages_for_planning(
                    system_prompt=system_prompt,
                    current_iteration=iteration,
                    trigger_prompt=trigger_prompt
                )
                logger.info(
                    f"{Fore.GREEN}[规划引擎] 使用 AgentRunMemory messages 模式，"
                    f"共 {len(messages)} 条消息（含历史记忆），iteration={iteration}{Style.RESET_ALL}"
                )
            else:
                # 兼容旧调用路径：无 run_memory 时降级为文字拼接 Prompt
                prompt = self._build_planning_prompt(
                    agent, task, available_tools, available_skills,
                    context, error_context, reflection_history
                )
                messages = [{"role": "user", "content": prompt}]
                logger.info(
                    f"{Fore.YELLOW}[规划引擎] 使用旧版文字拼接模式（未传入 run_memory）{Style.RESET_ALL}"
                )
            
            # ── 调用 LLM 生成规划决策 ──────────────────────────────────────────
            # 此处将准备好的 messages 数组发送给 LLM，等待规划结果
            logger.info(
                f"{Fore.BLUE}[规划引擎] 正在调用 LLM 生成计划 "
                f"(模型={agent.agent_config.planning_model}, messages条数={len(messages)}){Style.RESET_ALL}"
            )
            response = await self.llm_hub.infer(
                messages=messages,
                config=config
            )

            # ── LLM 响应原文（方便查看大模型规划了什么）────────────────────────
            logger.info(f"{Fore.GREEN}[规划引擎] LLM 返回原始规划内容:{Style.RESET_ALL}")
            logger.info(
                f"{Fore.GREEN}{response.content[:800] if response.content else '（空响应）'}{Style.RESET_ALL}"
            )

            # 解析计划：将 LLM 返回的 JSON 字符串解析为结构化 Plan 对象
            plan = self._parse_plan(response.content)
            
            logger.info(
                f"{Fore.GREEN}计划创建成功，共 {len(plan.steps)} 个步骤{Style.RESET_ALL}"
            )
            
            return plan
            
        except Exception as e:
            logger.error(f"{Fore.RED}创建计划失败: {e}{Style.RESET_ALL}")
            # 返回一个简单的兜底计划
            return Plan(
                steps=[
                    PlanStep(
                        action="final_answer",
                        content=f"抱歉，我无法为任务 '{task}' 创建执行计划。错误: {str(e)}"
                    )
                ],
                reasoning="规划失败，返回错误信息"
            )
    
    def _build_system_prompt(
        self,
        agent: Agent,
        available_tools: List[Tool],
        available_skills: List[Skill]
    ) -> str:
        """
        构建规划的系统提示词（system role）

        包含 Agent 角色定义、可用工具/技能/子Agent 清单以及 JSON 输出格式要求。
        这部分内容固定不变，适合放在 system 消息中。
        其余的历史上下文（错误记录、反思历史）通过 AgentRunMemory 注入 messages 数组，
        而不是文字拼接到这里——这样 LLM 能以「真实对话」而非「描述文本」理解历史。
        """
        tools_text = self._format_tools(available_tools)
        skills_text = self._format_skills(available_skills)
        child_agents_text = ", ".join(agent.child_agents) if agent.child_agents else "无"
        xxx = "xxx"

        return f"""你是 {agent.name}，{agent.description}

角色定义: {agent.role}

可用工具:
{tools_text}

可用技能:
{skills_text}

子 Agent:
{child_agents_text}

请制定详细的执行计划，以 JSON 格式返回。计划应包含以下字段：
{{
  "steps": [
    {{"action": "tool", "tool_name": "工具名称", "params": {{"参数名": "参数值"}}}},
    {{"action": "skill", "skill_id": "技能ID", "params": {{"参数名": "参数值"}}}},
    {{"action": "delegate", "agent_id": "子AgentID", "task": "委派的任务"}},
    {{"action": "final_answer", "content": "最终答案"}}
  ],
  "reasoning": "你的推理过程"
}}

注意事项：
1. 每个步骤只能有一个 action 字段，action 必须严格使用 "tool"、"skill"、"delegate"、"final_answer" 之一，禁止把工具名直接写作 action 值（例如不要写 "action": "database_query"，正确写法是 "action": "tool", "tool_name": "database_query"）
2. 最后一步必须是 final_answer，其 content 只需写一句简短的意图说明即可（例如 "根据以上查询结果回答用户"），禁止使用 {{{xxx}}} 或 [{xxx}] 这类占位符——系统会自动将前序步骤的真实数据合成为最终回答
3. 如果需要使用工具，确保工具名称正确
4. 如果需要调用技能，确保技能 ID 正确
5. 如果需要委派给子 Agent，确保子 Agent ID 在可用列表中
6. 【重要】每个工具步骤的参数必须是完整的、自包含的，不能依赖其他步骤的运行时输出。具体规则：
   - 数据库查询：必须用 JOIN 或子查询合并多表，不能使用 ? 占位符，禁止把前一步结果作为参数
   - 计算器：只能计算纯数学表达式（如 "1+2*3"），不能引用数据库字段名或变量
   - 如果需要先查询再计算，请在一条 SQL 里直接用 SUM/COUNT/AVG 等聚合函数完成
   - 【重要】如果后续步骤需要使用前序搜索结果的 URL 地址，必须使用以下占位符格式：
     * 使用 {{{{first_search_result_url}}}} 表示第一个搜索结果的 URL
     * 使用 {{{{first_search_result_title}}}} 表示第一个搜索结果的标题
     * 使用 {{{{first_search_result}}}} 表示第一个搜索结果的完整信息（包含 url, title, snippet）
     * 使用 {{{{last_tool_result}}}} 表示最后一个工具的执行结果
     * 例如：http_request 工具的 url 参数应该写成 "url": "{{{{first_search_result_url}}}}"

请只返回 JSON，不要包含其他文本。"""

    def _build_trigger_prompt(
        self,
        context: Optional[Dict[str, Any]] = None,
        user_rejected_tools: Optional[List[str]] = None
    ) -> str:
        """
        构建本轮规划的触发指令（最后一条 user 消息）

        当使用 run_memory messages 模式时，此方法生成最终的触发请求。
        历史错误/反思/用户操作已在 messages 数组前面的消息中呈现，
        这里只需给出补充约束和本轮规划执行指令。
        """
        lines = ["请基于以上历史记录（包含之前各轮的执行结果、工具调用结果和反思结论），制定本轮的执行计划。"]

        # 注入用户拒绝工具约束
        rejected = user_rejected_tools or []
        if rejected:
            lines.append(
                f"\n【强约束】用户已拒绝以下工具，本轮计划中严禁再次规划这些工具: {rejected}。"
                "若原任务必须依赖这些工具才能完成，请在 final_answer 中如实告知用户并解释原因。"
            )

        # 文件写入降级通知
        if "file_write" in rejected:
            lines.append(
                "\n【降级方案】若任务需要将内容保存到文件，且 file_write 已被禁用："
                "若有 python_executor 可用，请生成一段用户可在本机运行的 Python 写文件脚本交付；"
                "否则直接在最终答案中返回完整内容。"
            )

        lines.append("\n请只返回 JSON，不要包含其他文本。")
        return "\n".join(lines)

    def _build_planning_prompt(
        self,
        agent: Agent,
        task: str,
        available_tools: List[Tool],
        available_skills: List[Skill],
        context: Optional[Dict[str, Any]] = None,
        error_context: Optional[List[Dict[str, Any]]] = None,
        reflection_history: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """
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
        
        # 格式化工具列表
        tools_text = self._format_tools(available_tools)
        
        # 格式化技能列表
        skills_text = self._format_skills(available_skills)
        
        # 格式化子 Agent 列表
        child_agents_text = ", ".join(agent.child_agents) if agent.child_agents else "无"

        # 创建变量xxx
        xxx="xxx"
        
        # 构建 Prompt
        prompt = f"""你是 {agent.name}，{agent.description}

角色定义: {agent.role}

任务: {task}

可用工具:
{tools_text}

可用技能:
{skills_text}

子 Agent:
{child_agents_text}

请制定详细的执行计划，以 JSON 格式返回。计划应包含以下字段：
{{
  "steps": [
    {{"action": "tool", "tool_name": "工具名称", "params": {{"参数名": "参数值"}}}},
    {{"action": "skill", "skill_id": "技能ID", "params": {{"参数名": "参数值"}}}},
    {{"action": "delegate", "agent_id": "子AgentID", "task": "委派的任务"}},
    {{"action": "final_answer", "content": "最终答案"}}
  ],
  "reasoning": "你的推理过程"
}}

注意事项：
1. 每个步骤只能有一个 action 字段，action 必须严格使用 "tool"、"skill"、"delegate"、"final_answer" 之一，禁止把工具名直接写作 action 值（例如不要写 "action": "database_query"，正确写法是 "action": "tool", "tool_name": "database_query"）
2. 最后一步必须是 final_answer，其 content 只需写一句简短的意图说明即可（例如 "根据以上查询结果回答用户"），禁止使用 {xxx} 或 [xxx] 这类占位符——系统会自动将前序步骤的真实数据合成为最终回答
3. 如果需要使用工具，确保工具名称正确
4. 如果需要调用技能，确保技能 ID 正确
5. 如果需要委派给子 Agent，确保子 Agent ID 在可用列表中
6. 【重要】每个工具步骤的参数必须是完整的、自包含的，不能依赖其他步骤的运行时输出。具体规则：
   - 数据库查询：必须用 JOIN 或子查询合并多表，不能使用 ? 占位符，禁止把前一步结果作为参数
   - 计算器：只能计算纯数学表达式（如 "1+2*3"），不能引用数据库字段名或变量
   - 如果需要先查询再计算，请在一条 SQL 里直接用 SUM/COUNT/AVG 等聚合函数完成
   - 【重要】如果后续步骤需要使用前序搜索结果的 URL 地址，必须使用以下占位符格式：
     * 使用 {{first_search_result_url}} 表示第一个搜索结果的 URL
     * 使用 {{first_search_result_title}} 表示第一个搜索结果的标题
     * 使用 {{first_search_result}} 表示第一个搜索结果的完整信息（包含 url, title, snippet）
     * 使用 {{last_tool_result}} 表示最后一个工具的执行结果
     * 例如：http_request 工具的 url 参数应该写成 "url": "{{first_search_result_url}}"

请只返回 JSON，不要包含其他文本。
"""
        # NOTE: 若携带了跨迭代上下文（上一轮计划/执行/总结），注入到 Prompt。
        # 目标：让重规划时复用已获得的数据，避免重复执行同类查询步骤。
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

        # 动态注入替代方案提示词：只有当上下文真实包含对 file_write 的拒绝时，才提供降级方案
        if context and "file_write" in context.get("user_rejected_tools", []):
            prompt += """
【强约束：文件写入能力已被降级】
- **当用户已拒绝 file_write 且需求是保存内容到文件时**：若你有 python_executor 可用，应规划一步「用代码生成能力帮用户完成意图」——**生成并 print 出一段完整的、用户可在本机运行的 Python 脚本**，脚本内容为：将本应写入的数据写入本地文件（如 open(...).write(...)）。这样工具 output 即为该脚本源码，最终回答会完整交付脚本并说明「请将下方代码保存为 .py 文件后运行即可在本地生成文件」。仅当确实无可行方案时再告知无法完成。
"""

        # NOTE: 若本次规划携带了上一轮的错误上下文（重规划场景），则在 Prompt 末尾
        # 追加失败详情，引导 LLM 在新计划中规避已知问题路径
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

        # NOTE: 若携带了历史迭代反思记录（replan 场景），则将历次反思结论注入 Prompt。
        # 这是解决"无效迭代"问题的核心机制：
        # 当执行步骤技术上成功但任务未达成（如 Agent 因权限/能力边界无法完成任务），
        # error_context 为空但 reflection 已记录了问题。通过将历史反思注入 Prompt，
        # LLM 可从中学习改变策略，或在确实无法完成时明确告知用户原因而非无限循环。
        if reflection_history:
            history_lines = []
            for hist in reflection_history:
                iteration_num = hist.get("iteration", "?") + 1  # 显示时从 1 开始
                success = hist.get("success", False)
                feedback = hist.get("feedback", "")
                summary = hist.get("summary", "")
                needs_replan = hist.get("needs_replanning", False)
                status_str = "成功" if success else "失败"
                line = (
                    f"第 {iteration_num} 轮 [{status_str}] "
                    f"反馈: {feedback}" 
                    + (f" | 总结: {summary}" if summary else "")
                )
                history_lines.append(line)
            history_block = "\n".join(history_lines)
            # 获取可用智能体列表用于建议
            available_agents_text = ""
            if agent.child_agents:
                available_agents_text = f"\n【可用智能体】: {', '.join(agent.child_agents)}"
            else:
                # 如果没有子智能体但任务可能需要数据库访问，给出通用建议
                available_agents_text = "\n【提示】如果当前 Agent 无法完成该任务（如需要数据库访问权限），请在最终回答中建议用户返回主智能体（客服）寻求帮助"

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
        """
        格式化工具列表
        
        Args:
            tools: 工具列表
            
        Returns:
            str: 格式化后的工具描述
        """
        if not tools:
            return "无可用工具"
        
        formatted = []
        for tool in tools:
            formatted.append(f"- {tool.name}: {tool.schema.description}")
        
        return "\n".join(formatted)
    
    def _format_skills(self, skills: List[Skill]) -> str:
        """
        格式化技能列表
        
        Args:
            skills: 技能列表
            
        Returns:
            str: 格式化后的技能描述
        """
        if not skills:
            return "无可用技能"
        
        formatted = []
        for skill in skills:
            formatted.append(f"- {skill.skill_id} ({skill.name}): {skill.description}")
        
        return "\n".join(formatted)
    
    def _parse_plan(self, llm_output: str) -> Plan:
        """
        解析 LLM 返回的计划
        
        Args:
            llm_output: LLM 输出的文本
            
        Returns:
            Plan: 解析后的计划
        """
        logger.debug(f"{Fore.CYAN}解析 LLM 输出为计划{Style.RESET_ALL}")
        
        try:
            # 尝试提取 JSON
            llm_output = llm_output.strip()
            
            # 如果包含 markdown 代码块，提取其中的 JSON
            if "```json" in llm_output:
                start = llm_output.find("```json") + 7
                end = llm_output.find("```", start)
                llm_output = llm_output[start:end].strip()
            elif "```" in llm_output:
                start = llm_output.find("```") + 3
                end = llm_output.find("```", start)
                llm_output = llm_output[start:end].strip()
            
            # 解析 JSON
            plan_dict = json.loads(llm_output)
            
            # 构建 PlanStep 列表
            steps = []
            for step_dict in plan_dict.get("steps", []):
                action = step_dict.pop("action")
                steps.append(PlanStep(action=action, **step_dict))
            
            reasoning = plan_dict.get("reasoning", "")
            
            logger.info(f"{Fore.GREEN}计划解析成功，共 {len(steps)} 个步骤{Style.RESET_ALL}")
            
            return Plan(steps=steps, reasoning=reasoning)
            
        except json.JSONDecodeError as e:
            logger.error(f"{Fore.RED}JSON 解析失败: {e}{Style.RESET_ALL}")
            logger.error(f"{Fore.RED}LLM 输出: {llm_output[:200]}...{Style.RESET_ALL}")
            
            # 返回一个包含错误信息的计划
            return Plan(
                steps=[
                    PlanStep(
                        action="final_answer",
                        content=f"解析计划失败，LLM 返回的不是有效的 JSON 格式"
                    )
                ],
                reasoning="JSON 解析失败"
            )
        
        except Exception as e:
            logger.error(f"{Fore.RED}解析计划时发生错误: {e}{Style.RESET_ALL}")
            
            return Plan(
                steps=[
                    PlanStep(
                        action="final_answer",
                        content=f"解析计划时发生错误: {str(e)}"
                    )
                ],
                reasoning="解析错误"
            )


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Planning Engine 测试{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
    
    # 测试计划步骤
    step = PlanStep(action="tool", tool_name="search", params={"query": "test"})
    print(f"创建计划步骤: {step.to_dict()}")
    
    # 测试计划
    plan = Plan(
        steps=[step],
        reasoning="这是一个测试计划"
    )
    print(f"创建计划: {plan.to_dict()}")
    
    print(f"\n{Fore.GREEN}测试完成!{Style.RESET_ALL}\n")
