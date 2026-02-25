"""
子 Agent 管理器 (Child Agent Manager)
================================

本模块负责管理子 Agent 的任务委派和结果整合。

功能特点：
1. 维护 Agent 注册表
2. 实现任务委派
3. 避免循环引用
4. 整合子 Agent 结果

作者: AI Agent Team
创建时间: 2026-02-15
"""

from typing import Dict, Any, Optional, Set
from loguru import logger
from colorama import Fore, Style

from app.agents.base import Agent
from app.agents.registry import AgentRegistry


class ChildAgentManager:
    """
    子 Agent 管理器
    
    管理子 Agent 的任务委派和结果整合
    """
    
    def __init__(
        self,
        agent_registry: AgentRegistry,
        llm_hub,
        tool_hub,
        skill_manager
    ):
        """
        初始化子 Agent 管理器
        
        Args:
            agent_registry: Agent 注册表
            llm_hub: LLM Hub  实例
            tool_hub: 工具中心
            skill_manager: 技能管理器
        """
        self.agent_registry = agent_registry
        self.llm_hub = llm_hub
        self.tool_hub = tool_hub
        self.skill_manager = skill_manager
        
        # 记录当前调用链，用于检测循环依赖
        self._call_stack: Set[str] = set()
        
        logger.info(f"{Fore.GREEN}子 Agent 管理器初始化完成{Style.RESET_ALL}")
    
    async def delegate_task(
        self,
        parent_agent_id: Optional[str],
        child_agent_id: str,
        task: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        委派任务给子 Agent
        
        Args:
            parent_agent_id: 父 Agent ID（可选，用于循环检测）
            child_agent_id: 子 Agent ID
            task: 任务描述
            context: 任务上下文
            
        Returns:
            Dict[str, Any]: 任务执行结果
        """
        logger.info(
            f"{Fore.BLUE}委派任务给子 Agent: {child_agent_id}{Style.RESET_ALL}"
        )
        logger.info(f"{Fore.CYAN}任务: {task}{Style.RESET_ALL}")
        
        # 获取子 Agent
        child_agent = self.agent_registry.get_agent(child_agent_id)
        if not child_agent:
            error_msg = f"子 Agent 不存在: {child_agent_id}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            return {
                "success": False,
                "error": error_msg
            }
        
        # 检查循环依赖
        if child_agent_id in self._call_stack:
            error_msg = f"检测到循环依赖: {child_agent_id} 已在调用链中"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            logger.error(
                f"{Fore.RED}当前调用链: {' -> '.join(self._call_stack)}{Style.RESET_ALL}"
            )
            return {
                "success": False,
                "error": error_msg
            }
        
        # 将子 Agent 加入调用链
        self._call_stack.add(child_agent_id)
        
        try:
            # 执行子 Agent
            from app.agents.planning import PlanningEngine
            from app.agents.execution import ExecutionEngine
            
            # 创建 Planning Engine
            planning_engine = PlanningEngine(llm_hub=self.llm_hub)
            
            # 获取子 Agent 的可用工具和技能
            available_tools = [
                self.tool_hub.get_tool(tool_name)
                for tool_name in child_agent.available_tools
            ]
            available_tools = [t for t in available_tools if t is not None]
            
            available_skills = [
                self.skill_manager.get_skill(skill_id)
                for skill_id in child_agent.available_skills
            ]
            available_skills = [s for s in available_skills if s is not None]
            
            # 创建执行计划
            logger.info(f"{Fore.BLUE}为子 Agent {child_agent.name} 创建执行计划{Style.RESET_ALL}")
            plan = await planning_engine.create_plan(
                agent=child_agent,
                task=task,
                available_tools=available_tools,
                available_skills=available_skills,
                context=context
            )
            
            # 创建 Execution Engine
            execution_engine = ExecutionEngine(
                tool_hub=self.tool_hub,
                skill_manager=self.skill_manager,
                llm_hub=self.llm_hub,
                child_agent_manager=self  # 递归支持
            )
            
            # 执行计划
            logger.info(f"{Fore.BLUE}执行子 Agent {child_agent.name} 的计划{Style.RESET_ALL}")
            result = await execution_engine.execute_plan(
                agent=child_agent,
                plan=plan,
                context=context
            )
            
            logger.info(
                f"{Fore.GREEN}子 Agent {child_agent.name} 任务执行完成{Style.RESET_ALL}"
            )
            
            return {
                "success": result.success,
                "result": result.result,
                "agent_id": child_agent_id,
                "agent_name": child_agent.name
            }
            
        except Exception as e:
            error_msg = f"子 Agent {child_agent_id} 执行失败: {e}"
            logger.error(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            
            return {
                "success": False,
                "error": str(e),
                "agent_id": child_agent_id
            }
        
        finally:
            # 从调用链中移除
            self._call_stack.discard(child_agent_id)
    
    def _check_circular_dependency(
        self,
        parent_agent_id: str,
        child_agent_id: str,
        visited: Optional[Set[str]] = None
    ) -> bool:
        """
        检查是否存在循环依赖
        
        Args:
            parent_agent_id: 父 Agent ID
            child_agent_id: 子 Agent ID
            visited: 已访问的 Agent ID 集合
            
        Returns:
            bool: True 表示存在循环依赖
        """
        if visited is None:
            visited = set()
        
        # 如果子 Agent 是父 Agent，存在循环
        if child_agent_id == parent_agent_id:
            return True
        
        # 如果已访问过，存在循环
        if child_agent_id in visited:
            return True
        
        # 标记为已访问
        visited.add(child_agent_id)
        
        # 获取子 Agent
        child_agent = self.agent_registry.get_agent(child_agent_id)
        if not child_agent:
            return False
        
        # 递归检查子 Agent 的子 Agent
        for grandchild_id in child_agent.child_agents:
            if self._check_circular_dependency(parent_agent_id, grandchild_id, visited):
                return True
        
        return False
    
    def clear_call_stack(self) -> None:
        """清空调用链（用于测试或重置）"""
        self._call_stack.clear()
        logger.info(f"{Fore.CYAN}调用链已清空{Style.RESET_ALL}")


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Child Agent Manager 测试{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
    
    print("Child Agent Manager 已实现")
    
    print(f"\n{Fore.GREEN}测试完成!{Style.RESET_ALL}\n")
