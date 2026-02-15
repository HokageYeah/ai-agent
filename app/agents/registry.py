"""
Agent 注册表 (Agent Registry)
================================

本模块负责管理所有可用的 Agent 实例。

功能特点：
1. Agent 的注册和查询
2. Agent 的生命周期管理
3. 防止重复注册

作者: AI Agent Team
创建时间: 2026-02-15
"""

from typing import Dict, List, Optional
from loguru import logger
from colorama import Fore, Style

from app.agents.base import Agent


class AgentRegistry:
    """
    Agent 注册表
    
    管理所有可用的 Agent 实例，提供注册、查询功能
    """
    
    def __init__(self):
        """初始化 Agent 注册表"""
        self._agents: Dict[str, Agent] = {}
        logger.info(f"{Fore.GREEN}Agent 注册表初始化完成{Style.RESET_ALL}")
    
    def register_agent(self, agent: Agent) -> None:
        """
        注册 Agent
        
        Args:
            agent: Agent 实例
        """
        if agent.agent_id in self._agents:
            logger.warning(
                f"{Fore.YELLOW}覆盖已存在的 Agent: {agent.agent_id} ({agent.name}){Style.RESET_ALL}"
            )
        
        self._agents[agent.agent_id] = agent
        logger.info(
            f"{Fore.CYAN}注册 Agent: {agent.name} (ID: {agent.agent_id}), "
            f"能力: {', '.join(agent.capabilities)}{Style.RESET_ALL}"
        )
    
    def get_agent(self, agent_id: str) -> Optional[Agent]:
        """
        获取 Agent
        
        Args:
            agent_id: Agent ID
            
        Returns:
            Optional[Agent]: Agent 实例，若不存在则返回 None
        """
        agent = self._agents.get(agent_id)
        if not agent:
            logger.warning(f"{Fore.RED}Agent 不存在: {agent_id}{Style.RESET_ALL}")
        else:
            logger.debug(f"{Fore.BLUE}获取 Agent: {agent.name} (ID: {agent_id}){Style.RESET_ALL}")
        
        return agent
    
    def list_agents(self) -> List[Agent]:
        """
        列出所有 Agent
        
        Returns:
            List[Agent]: 所有 Agent 列表
        """
        logger.debug(f"{Fore.BLUE}列出所有 Agent，共 {len(self._agents)} 个{Style.RESET_ALL}")
        return list(self._agents.values())
    
    def unregister_agent(self, agent_id: str) -> bool:
        """
        注销 Agent
        
        Args:
            agent_id: Agent ID
            
        Returns:
            bool: 是否成功注销
        """
        if agent_id in self._agents:
            agent = self._agents.pop(agent_id)
            logger.info(
                f"{Fore.CYAN}注销 Agent: {agent.name} (ID: {agent_id}){Style.RESET_ALL}"
            )
            return True
        else:
            logger.warning(
                f"{Fore.YELLOW}无法注销不存在的 Agent: {agent_id}{Style.RESET_ALL}"
            )
            return False
    
    def clear(self) -> None:
        """清空所有 Agent"""
        count = len(self._agents)
        self._agents.clear()
        logger.info(f"{Fore.CYAN}清空注册表，移除了 {count} 个 Agent{Style.RESET_ALL}")


# =============================================================================
# 全局单例实例
# =============================================================================

# 创建全局 Agent 注册表实例
_global_registry = AgentRegistry()


def get_global_registry() -> AgentRegistry:
    """
    获取全局 Agent 注册表实例
    
    Returns:
        AgentRegistry: 全局注册表实例
    """
    return _global_registry
