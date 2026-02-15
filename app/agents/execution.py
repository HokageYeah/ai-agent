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

from typing import Dict, List, Any, Optional
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
        child_agent_manager=None
    ):
        """
        初始化执行引擎
        
        Args:
            tool_hub: 工具中心
            skill_manager: 技能管理器
            llm_hub: LLM Hub 实例
            child_agent_manager: 子 Agent 管理器（可选）
        """
        self.tool_hub = tool_hub
        self.skill_manager = skill_manager
        self.llm_hub = llm_hub
        self.child_agent_manager = child_agent_manager
        
        logger.info(f"{Fore.GREEN}执行引擎初始化完成{Style.RESET_ALL}")
    
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
                
                # 执行步骤
                step_result = await self._execute_step(agent, step, context)
                step_results.append(step_result)
                
                # 如果是 final_answer，直接返回
                if step.action == "final_answer":
                    final_result = step.params.get("content", "")
                    
                    # 鲁棒性增强：如果 final_answer 为空，尝试收集之前步骤的结果
                    if not final_result and step_results:
                        logger.warning(
                            f"{Fore.YELLOW}final_answer 为空，尝试使用之前步骤的结果{Style.RESET_ALL}"
                        )
                        # 收集所有非空的步骤结果
                        results = []
                        for res in step_results:
                            if res.get("success") and res.get("result"):
                                action = res.get("action", "unknown")
                                val = str(res.get("result"))
                                results.append(f"[{action}]: {val}")
                        
                        if results:
                            final_result = "自动聚合的执行结果：\n" + "\n".join(results)
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
    
    async def _execute_step(
        self,
        agent: Agent,
        step: PlanStep,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        执行单个步骤
        
        Args:
            agent: Agent 实例
            step: 计划步骤
            context: 执行上下文
            
        Returns:
            Dict[str, Any]: 步骤执行结果
        """
        try:
            if step.action == "tool":
                return await self._execute_tool(step)
            elif step.action == "skill":
                return await self._execute_skill(step, context, agent)
            elif step.action == "delegate":
                return await self._delegate_to_agent(step)
            elif step.action == "final_answer":
                return {
                    "success": True,
                    "result": step.params.get("content", ""),
                    "action": "final_answer"
                }
            else:
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
    
    async def _execute_tool(self, step: PlanStep) -> Dict[str, Any]:
        """
        执行工具调用
        
        Args:
            step: 计划步骤
            
        Returns:
            Dict[str, Any]: 执行结果
        """
        tool_name = step.params.get("tool_name")
        params = step.params.get("params", {})
        
        logger.info(f"{Fore.CYAN}调用工具: {tool_name}{Style.RESET_ALL}")
        
        # 获取工具
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
        
        # 执行工具
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
        agent: Optional[Agent] = None
    ) -> Dict[str, Any]:
        """
        执行技能调用
        
        Args:
            step: 计划步骤
            context: 执行上下文
            
        Returns:
            Dict[str, Any]: 执行结果
        """
        skill_id = step.params.get("skill_id")
        params = step.params.get("params", {})
        
        logger.info(f"{Fore.CYAN}调用技能: {skill_id}{Style.RESET_ALL}")
        
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
                
            config = InferenceConfig(
                model=model,
                temperature=0.7
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
    
    async def _delegate_to_agent(self, step: PlanStep) -> Dict[str, Any]:
        """
        委派给子 Agent
        
        Args:
            step: 计划步骤
            
        Returns:
            Dict[str, Any]: 执行结果
        """
        agent_id = step.params.get("agent_id")
        task = step.params.get("task")
        
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
        
        # 委派任务（parent_agent_id 设为 None，因为在执行引擎层面不跟踪父 Agent）
        try:
            result = await self.child_agent_manager.delegate_task(
                parent_agent_id=None,  # 添加缺失的参数
                child_agent_id=agent_id,
                task=task
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
