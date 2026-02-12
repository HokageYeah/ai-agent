from typing import Dict, List, Optional
from loguru import logger
from colorama import Fore, Style
from app.skills.base import Skill

class SkillManager:
    """
    技能管理器
    
    负责技能的注册、查询和管理
    """
    
    def __init__(self):
        self._skills: Dict[str, Skill] = {}
        logger.info(f"{Fore.BLUE}SkillManager initialized.{Style.RESET_ALL}")
    
    def register_skill(self, skill: Skill):
        """
        注册技能
        
        Args:
            skill: Skill 实例
        """
        if skill.skill_id in self._skills:
            logger.warning(f"{Fore.YELLOW}Overwriting existing skill: {skill.skill_id}{Style.RESET_ALL}")
        
        self._skills[skill.skill_id] = skill
        logger.debug(f"Registered skill: {Fore.GREEN}{skill.name} ({skill.skill_id}){Style.RESET_ALL}")
    
    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """
        获取技能
        
        Args:
            skill_id: 技能 ID
            
        Returns:
            Optional[Skill]: 技能实例
        """
        skill = self._skills.get(skill_id)
        if not skill:
            logger.warning(f"{Fore.RED}Skill not found: {skill_id}{Style.RESET_ALL}")
        return skill
    
    def list_skills(self) -> List[Skill]:
        """
        列出所有技能
        
        Returns:
            List[Skill]: 技能列表
        """
        return list(self._skills.values())

    # Task 0.5 仅涵盖核心抽象，实际执行逻辑 (execute_skill) 通常在 Agent 或 Workflow 引擎中结合 LLM Hub 实现
    # 但根据设计文档 6.3 节，SkillManager 也可以包含 execute_skill 方法作为一种便捷入口
    # 在此阶段我们先专注于定义和管理
