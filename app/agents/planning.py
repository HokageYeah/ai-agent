"""
规划引擎 (Planning Engine)
================================

本模块负责为 Agent 创建执行计划。

功能特点：
1. 基于任务和可用资源生成执行计划
2. 使用 LLM 进行智能规划
3. 支持工具、技能、子 Agent 的组合使用
4. 返回结构化的 JSON 计划

作者: AI Agent Team
创建时间: 2026-02-15
"""

import json
from typing import Dict, List, Any, Optional
from loguru import logger
from colorama import Fore, Style

from app.agents.base import Agent
from app.tools.base import Tool
from app.skills.base import Skill


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
    
    def __init__(self, llm_hub):
        """
        初始化规划引擎
        
        Args:
            llm_hub: LLM Hub 实例 (InferenceEngine)
        """
        self.llm_hub = llm_hub
        logger.info(f"{Fore.GREEN}规划引擎初始化完成{Style.RESET_ALL}")
    
    async def create_plan(
        self,
        agent: Agent,
        task: str,
        available_tools: List[Tool],
        available_skills: List[Skill],
        context: Optional[Dict[str, Any]] = None
    ) -> Plan:
        """
        创建执行计划
        
        Args:
            agent: Agent 实例
            task: 任务描述
            available_tools: 可用工具列表
            available_skills: 可用技能列表
            context: 额外上下文信息
            
        Returns:
            Plan: 执行计划
        """
        logger.info(
            f"{Fore.BLUE}开始为 Agent '{agent.name}' 创建执行计划{Style.RESET_ALL}"
        )
        logger.info(f"{Fore.CYAN}任务: {task}{Style.RESET_ALL}")
        
        # 构建规划 Prompt
        prompt = self._build_planning_prompt(
            agent, task, available_tools, available_skills, context
        )
        
        # 使用 LLM 生成计划
        logger.info(f"{Fore.BLUE}调用 LLM 生成计划...{Style.RESET_ALL}")
        
        try:
            from app.llm_hub.inference import InferenceConfig
            
            config = InferenceConfig(
                model=agent.agent_config.planning_model,
                temperature=0.7,
                max_tokens=2048
            )
            
            response = await self.llm_hub.infer(
                messages=[{"role": "user", "content": prompt}],
                config=config
            )
            
            # 解析计划
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
    
    def _build_planning_prompt(
        self,
        agent: Agent,
        task: str,
        available_tools: List[Tool],
        available_skills: List[Skill],
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        构建规划 Prompt
        
        Args:
            agent: Agent 实例
            task: 任务描述
            available_tools: 可用工具列表
            available_skills: 可用技能列表
            context: 额外上下文
            
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

请只返回 JSON，不要包含其他文本。
"""
        
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
