"""
反思引擎 (Reflection Engine)
================================

本模块负责评估执行结果并决定下一步行动。

功能特点：
1. 分析执行结果的质量
2. 判断任务是否完成
3. 决定是否需要重新规划
4. 生成结果总结

作者: AI Agent Team
创建时间: 2026-02-15
"""

import json
from typing import Dict, Any, Optional, List
from loguru import logger
from colorama import Fore, Style

from app.agents.base import Agent
from app.agents.execution import ExecutionResult


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
        available_tools: Optional[List] = None
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
        logger.info(f"{Fore.CYAN}任务: {task}{Style.RESET_ALL}")
        logger.info(
            f"{Fore.CYAN}执行状态: {'成功' if execution_result.success else '失败'}{Style.RESET_ALL}"
        )
        
        # 查看是否携带错误上下文（多步骤失败场景）
        if error_context:
            logger.info(
                f"{Fore.YELLOW}[反思引擎] 本次反思携带 {len(error_context)} 条错误信息，将提升判断质量{Style.RESET_ALL}"
            )

        # 构建反思 Prompt
        prompt = self._build_reflection_prompt(task, execution_result, error_context)
        
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
            
            response = await self.llm_hub.infer(
                messages=[{"role": "user", "content": prompt}],
                config=config
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
- 如果 Agent 返回"无法完成"、"没有权限"、"无法访问"、"超出能力范围"等
- 如果用户，说明任务未完成问题没有被真正解决，即使执行不报错，success 也应为 false
- 如果当前 Agent 确实无法完成任务（例如需要数据库权限但没有），should_continue 应为 false
- should_continue 由你根据任务完成情况和 Agent 能力边界综合判断：如果还有希望完成就 true，如果确实无法完成就 false

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
