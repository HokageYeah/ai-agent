"""
反思引擎 (Reflection Engine)
================================

本模块负责评估执行结果并决定下一步行动。

功能特点：
1. 分析执行结果的质量
2. 判断任务是否完成
3. 决定是否需要重新规划
4. 生成结果总结
5. 支持 AgentRunMemory：历史记忆以 OpenAI messages 格式传递，无需文字拼接

作者: AI Agent Team
创建时间: 2026-02-15
更新时间: 2026-03-06（集成 AgentRunMemory 记忆系统）
"""

import json
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from loguru import logger
from colorama import Fore, Style

from app.agents.base import Agent
from app.agents.execution import ExecutionResult

# NOTE: 使用 TYPE_CHECKING 避免循环导入
if TYPE_CHECKING:
    from app.memory.agent_run_memory import AgentRunMemory


class ReflectionResult:
    """反思结果"""

    def __init__(
        self,
        success: bool,
        needs_replanning: bool,
        feedback: str,
        summary: str,
        should_continue: Optional[bool] = None
    ):
        """
        初始化反思结果

        Args:
            success: 任务是否成功完成
            needs_replanning: 是否需要重新规划
            feedback: 改进建议
            summary: 结果总结
            should_continue: LLM 判断是否应该继续迭代（True=继续, False=结束, None=由执行器决定）
        """
        self.success = success
        self.needs_replanning = needs_replanning
        self.feedback = feedback
        self.summary = summary
        self.should_continue = should_continue

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            "success": self.success,
            "needs_replanning": self.needs_replanning,
            "feedback": self.feedback,
            "summary": self.summary
        }
        if self.should_continue is not None:
            result["should_continue"] = self.should_continue
        return result


class ReflectionEngine:
    """
    反思引擎
    
    评估执行结果并决定下一步行动
    """
    
    def __init__(self, llm_hub, tool_hub=None):
        """
        初始化反思引擎
        
        Args:
            llm_hub: LLM Hub 实例 (InferenceEngine)
            tool_hub: 工具中心实例（可选），用于获取工具定义
        """
        self.llm_hub = llm_hub
        self.tool_hub = tool_hub
        logger.info(f"{Fore.GREEN}反思引擎初始化完成{Style.RESET_ALL}")
    
    async def reflect(
        self,
        agent: Agent,
        task: str,
        execution_result: ExecutionResult,
        error_context: Optional[List[Dict[str, Any]]] = None,
        available_tools: Optional[List] = None,
        # NOTE: AgentRunMemory 集成入参——当传入时，优先用 messages 格式传递历史记忆，
        #       而非把错误历史文字拼接到 prompt，远胜于文字拼接方式。
        run_memory: Optional[Any] = None,
        iteration: int = 0
    ) -> ReflectionResult:
        """
        反思执行结果

        Args:
            agent: Agent 实例
            task: 原始任务
            execution_result: 执行结果
            error_context: 错误上下文（所有失败步骤的详情），可选

        Returns:
            ReflectionResult: 反思结果
        """
        logger.info(
            f"{Fore.BLUE}开始反思任务执行结果{Style.RESET_ALL}"
        )
        # todo 一会解开注释
        # logger.info(f"{Fore.CYAN}任务: {task}{Style.RESET_ALL}")
        logger.info(
            f"{Fore.CYAN}执行状态: {'成功' if execution_result.success else '失败'}{Style.RESET_ALL}"
        )
        
        # 查看是否携带错误上下文（多步骤失败场景）
        if error_context:
            logger.info(
                f"{Fore.YELLOW}[反思引擎] 本次反思携带 {len(error_context)} 条错误信息，将提升判断质量{Style.RESET_ALL}"
            )

        # 使用 LLM 进行反思
        logger.info(f"{Fore.BLUE}调用 LLM 进行反思...{Style.RESET_ALL}")
        
        try:
            from app.llm_hub.inference import InferenceConfig
            
            # NOTE: 同规划阶段，反思阶段也只向 LLM 传递该 Agent 有权使用的工具定义。
            # 若传入禁用工具的定义，LLM 可能在 feedback 中建议使用禁用工具，误导重规划。
            tools = []
            if self.tool_hub:
                if available_tools:
                    allowed_tool_names = {t.name for t in available_tools}
                    all_schemas = self.tool_hub.get_schemas()
                    tools = [
                        s for s in all_schemas
                        if s.get("function", {}).get("name") in allowed_tool_names
                    ]
                    logger.debug(
                        f"{Fore.CYAN}[反思引擎] 工具定义已过滤: "
                        f"授权 {len(tools)}/{len(all_schemas)} 个{Style.RESET_ALL}"
                    )
                else:
                    tools = self.tool_hub.get_schemas()
                    logger.debug(f"{Fore.CYAN}[反思引擎] 已注册 {len(tools)} 个工具定义{Style.RESET_ALL}")
            
            config = InferenceConfig(
                model=agent.agent_config.execution_model,
                temperature=0.5,
                max_tokens=1024,
                tools=tools
            )

            # ── 核心改造：优先使用 run_memory messages 格式传递历史记忆 ───────
            # 当 run_memory 存在时，通过 build_messages_for_reflection() 让 LLM 看到本轮
            # 完整的工具调用记录和历史反思，准确度远优于文字拼接。
            # 当 run_memory 不存在时，降级为旧的 prompt 文字拼接。
            if run_memory is not None:
                reflect_system = self._build_reflection_system_prompt()
                reflect_trigger = self._build_reflection_trigger(
                    execution_result=execution_result,
                    error_context=error_context
                )
                messages = run_memory.build_messages_for_reflection(
                    system_prompt=reflect_system,
                    current_iteration=iteration,
                    trigger_prompt=reflect_trigger
                )
                logger.info(
                    f"{Fore.GREEN}[反思引擎] 使用 AgentRunMemory messages 模式，"
                    f"共 {len(messages)} 条消息，iteration={iteration}{Style.RESET_ALL}"
                )
            else:
                # 兼容旧调用路径
                prompt = self._build_reflection_prompt(task, execution_result, error_context)
                messages = [{"role": "user", "content": prompt}]
                logger.info(
                    f"{Fore.YELLOW}[反思引擎] 使用旧版文字拼接模式（未传入 run_memory）{Style.RESET_ALL}"
                )
            
            # ── 调用 LLM 进行反思评估 ────────────────────────────────────────
            # 此处将准备好的 messages 数组（含本轮所有工具调用记录）发送给 LLM
            logger.info(
                f"{Fore.BLUE}[反思引擎] 正在调用 LLM 进行反思评估 "
                f"(模型={agent.agent_config.execution_model}, messages条数={len(messages)}){Style.RESET_ALL}"
            )
            response = await self.llm_hub.infer(
                messages=messages,
                config=config
            )

            # ── LLM 响应原文（方便查看大模型对本轮执行的判断）──────────────────
            logger.info(f"{Fore.GREEN}[反思引擎] LLM 返回原始反思内容:{Style.RESET_ALL}")
            logger.info(
                f"{Fore.GREEN}{response.content[:600] if response.content else '（空响应）'}{Style.RESET_ALL}"
            )

            # NOTE: 将 execution_result 传入解析方法，用于当 LLM 输出无效时的智能兜底
            reflection = self._parse_reflection(response.content, execution_result)
            
            logger.info(
                f"{Fore.GREEN}反思完成: success={reflection.success}, "
                f"needs_replanning={reflection.needs_replanning}{Style.RESET_ALL}"
            )
            
            return reflection
            
        except Exception as e:
            logger.error(f"{Fore.RED}反思失败（LLM 调用异常）: {e}{Style.RESET_ALL}")
            
            # NOTE: 当 LLM 调用本身失败时，以执行结果为准：
            #       - 执行成功 → success=True, needs_replanning=False（避免无效重试）
            #       - 执行失败 → success=False, needs_replanning=True（允许重试）
            return ReflectionResult(
                success=execution_result.success,
                needs_replanning=not execution_result.success,
                feedback=f"反思 LLM 调用异常: {str(e)}",
                summary=f"执行{'成功' if execution_result.success else '失败'}（反思无法完成）"
            )
    
    def _build_reflection_system_prompt(self) -> str:
        """
        构建反思的系统提示词（system role）
        包含反思角色定义和输出格式要求。
        历史执行数据通过 AgentRunMemory.build_messages_for_reflection() 注入。
        """
        return """你是一个 AI Agent 的反思评估模块。你的职责是审查上方展示的执行过程，
并对任务完成情况做出客观判断。请以 JSON 格式返回评估结果：
{{
  "success": true/false,
  "needs_replanning": true/false,
  "should_continue": true/false,
  "feedback": "改进建议",
  "summary": "结果总结"
}}

【重要判断标准】：
- 如果 Agent 返回"无法完成"、"没有权限"、"无法访问"、"超出能力范围"等，说明任务真实因为环境或能力限制被中断。
- 如果历史消息中包含 "[用户操作通知]用户拒绝了" 这类消息，success 必须为 false。
- 对于其他情况，如果问题没有被真正解决，即使执行不报错，success 也应为 false。
- should_continue 由你根据任务完成情况、Agent 能力边界及可用工具综合判断：还有希望完成即给出 true，确实无法完成即给出 false。
请只返回 JSON，不要包含其他文本。"""

    def _build_reflection_trigger(
        self,
        execution_result: ExecutionResult,
        error_context: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """
        构建反思的触发指令（最后一条 user 消息）
        
        当使用 run_memory messages 模式时，工具调用结果已在 messages 中呈现，
        这里只需补充说明整体执行状态和要求进行反思。
        """
        lines = [
            f"当前轮执行状态: {'\u6210\u529f' if execution_result.success else '\u5931\u8d25'}",
            f"整体结果: {str(execution_result.result)[:300]}"
        ]

        if error_context:
            error_lines = []
            for idx, err in enumerate(error_context, 1):
                step_desc = err.get("step_desc", "未知步骤")
                error_msg = err.get("error_msg", "")
                error_type = err.get("error_type", "")
                suggestion = err.get("suggestion", "")
                line = f"{idx}. [{error_type}] {step_desc}: {error_msg}"
                if suggestion:
                    line += f" (建议: {suggestion})"
                error_lines.append(line)
            lines.append(f"\n本轮执行中发现 {len(error_context)} 个错误\uff1a\n" + "\n".join(error_lines))

        # 用户拒绝评估约束
        if execution_result.error and "[UserRejected]" in execution_result.error:
            lines.append(
                "\n【降级方案评估】若本轮已使用 python_executor 成功生成了用户可本地运行的脚本，success=true；"
                "若尚未完成递交，可建议下一轮用 python_executor 生成脚本。"
            )

        lines.append("\n请基于以上执行过程和状态，对任务完成情况进行反思评估。请只返回 JSON，不要包含其他文本。")
        return "\n".join(lines)

    def _build_reflection_prompt(
        self,
        task: str,
        execution_result: ExecutionResult,
        error_context: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """
        构建反思 Prompt
        
        Args:
            task: 原始任务
            execution_result: 执行结果
            
        Returns:
            str: Prompt 文本
        """
        logger.debug(f"{Fore.CYAN}构建反思 Prompt{Style.RESET_ALL}")
        
        # 格式化执行结果
        result_text = f"""
执行状态: {'成功' if execution_result.success else '失败'}
最终结果: {execution_result.result}
步骤结果数量: {len(execution_result.step_results)}
错误信息: {execution_result.error if execution_result.error else '无'}
"""
        
        prompt = f"""请评估以下任务的执行结果：

任务: {task}

执行结果:
{result_text}
"""

        # NOTE: 若携带错误上下文，将具体失败步骤注入 Prompt，让 LLM 知情所有错误
        if error_context:
            error_lines = []
            for idx, err in enumerate(error_context, 1):
                step_desc = err.get("step_desc", "未知步骤")
                error_msg = err.get("error_msg", "")
                error_type = err.get("error_type", "")
                suggestion = err.get("suggestion", "")
                line = f"{idx}. [{error_type}] {step_desc}: {error_msg}"
                if suggestion:
                    line += f" (建议: {suggestion})"
                error_lines.append(line)
            error_summary = "\n".join(error_lines)
            prompt += f"""
执行过程中发现以下{len(error_context)}个错误：
{error_summary}
"""
            logger.info(
                f"{Fore.YELLOW}[反思引擎] 已将 {len(error_context)} 条错误信息注入反思 Prompt{Style.RESET_ALL}"
            )

        prompt += """
请回答以下问题：
1. 用户任务是否真正完成？（注意：执行不报错≠任务完成，要看用户问题是否得到解决）
2. 结果质量如何？
3. 是否需要改进？
4. 下一步应该做什么？

请以 JSON 格式返回评估结果：
{{
  "success": true/false,
  "needs_replanning": true/false,
  "should_continue": true/false,
  "feedback": "改进建议",
  "summary": "结果总结"
}}

【重要判断标准】：
- 如果 Agent 返回"无法完成"、"没有权限"、"无法访问"、"超出能力范围"等，说明任务真实因为环境或能力限制被中断。
- 如果错误上下文中包含 [UserRejected] 类型错误，说明任务的某个特定操作已被用户明确拒绝/取消，此时 success 必须为 false。
- 对于其他情况，如果问题没有被真正解决，即使执行不报错，success 也应为 false
- should_continue 由你根据任务完成情况、Agent 能力边界及可用工具（排除已拒绝工具后）综合判断：如果还有希望完成即给出 true，如果确实无法完成即给出 false。
"""

        # 动态注入替代方案评估规则：仅当执行结果的错误信息中包含明确的拒绝记录时，才要求评估替代方案
        if execution_result.error and "[UserRejected]" in execution_result.error:
            prompt += """
【降级方案评估约束】
- 本次执行中包含了被用户拒绝的操作。**替代方案是否已落实**：若本轮已使用 python_executor 成功**生成了用户可本地运行的脚本**（工具返回 success 且有 output，且 output 为可写入文件的 Python 代码）或生成了本应写入的完整内容，且最终回答中已完整交付该脚本/内容并说明用户如何运行或保存，则视为**在用户拒绝写文件的前提下已用代码生成能力帮助完成意图**，success=true，needs_replanning=false。不要建议“用 http_request 等其他工具直接保存文件”（无此能力）。
- 若本轮尚未用 python_executor 生成可运行脚本或未在最终回答中完整交付，则可建议下一轮「用 python_executor 生成一段用户可本机运行的写文件脚本并交付」。若确实无可行方案则 should_continue=false。
"""

        prompt += """
请只返回 JSON，不要包含其他文本。
"""
        
        # todo 一会解开注释
        # logger.info(f"{Fore.CYAN}反思 Prompt: {prompt}{Style.RESET_ALL}")
        # logger.info(f"{Fore.CYAN}执行结果: {result_text}{Style.RESET_ALL}")
        # logger.info(f"{Fore.CYAN}任务: {task}{Style.RESET_ALL}")
        # logger.info(f"{Fore.CYAN}执行状态: {'成功' if execution_result.success else '失败'}{Style.RESET_ALL}")
        # logger.info(f"{Fore.CYAN}错误信息: {execution_result.error if execution_result.error else '无'}{Style.RESET_ALL}")
        # logger.info(f"{Fore.CYAN}步骤结果数量: {len(execution_result.step_results)}{Style.RESET_ALL}")
        # logger.info(f"{Fore.CYAN}最终结果: {execution_result.result}{Style.RESET_ALL}")
        
        return prompt
    
    def _parse_reflection(self, llm_output: str, execution_result=None) -> ReflectionResult:
        """
        解析 LLM 返回的反思结果
        
        Args:
            llm_output: LLM 输出的文本
            execution_result: 执行结果（可选），用于 JSON 解析失败时的智能兜底
            
        Returns:
            ReflectionResult: 解析后的反思结果
        """
        logger.debug(f"{Fore.CYAN}解析 LLM 输出为反思结果{Style.RESET_ALL}")
        
        # NOTE: 提前从 execution_result 提取执行状态，用于各种 fallback 场景
        exec_success = execution_result.success if execution_result else False
        
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
            reflection_dict = json.loads(llm_output)

            result = ReflectionResult(
                success=reflection_dict.get("success", False),
                needs_replanning=reflection_dict.get("needs_replanning", False),
                feedback=reflection_dict.get("feedback", ""),
                summary=reflection_dict.get("summary", ""),
                should_continue=reflection_dict.get("should_continue")  # LLM 自主判断是否继续
            )

            logger.info(
                f"{Fore.GREEN}反思结果解析成功: "
                f"success={result.success}, should_continue={result.should_continue}{Style.RESET_ALL}"
            )
            
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"{Fore.RED}JSON 解析失败: {e}{Style.RESET_ALL}")
            logger.error(f"{Fore.RED}LLM 输出: {llm_output[:200]}...{Style.RESET_ALL}")
            
            # NOTE: JSON 解析失败时以执行结果为准：
            #       - 执行成功 → needs_replanning=False（无需重试）
            #       - 执行失败 → needs_replanning=True（允许重试）
            # 这样能避免因 LLM 输出格式问题导致已成功的执行被无限重试
            return ReflectionResult(
                success=exec_success,
                needs_replanning=not exec_success,
                feedback="LLM 反思输出格式无效（非 JSON）",
                summary=llm_output[:200] if llm_output else "无法生成总结"
            )
        
        except Exception as e:
            logger.error(f"{Fore.RED}解析反思结果时发生错误: {e}{Style.RESET_ALL}")
            
            return ReflectionResult(
                success=exec_success,
                needs_replanning=not exec_success,
                feedback=f"解析错误: {str(e)}",
                summary="解析失败"
            )


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Reflection Engine 测试{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
    
    # 测试反思结果
    result = ReflectionResult(
        success=True,
        needs_replanning=False,
        feedback="执行得很好",
        summary="任务成功完成"
    )
    print(f"创建反思结果: {result.to_dict()}")
    
    print(f"\n{Fore.GREEN}测试完成!{Style.RESET_ALL}\n")
