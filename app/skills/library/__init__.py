"""
技能库模块

本模块包含预定义的技能集合，每个技能都是一个完整的能力单元。

可用技能:
- DATA_ANALYSIS_SKILL: 数据分析技能
- CODE_GENERATION_SKILL: 代码生成技能
- TEXT_WRITING_SKILL: 文本写作技能
- TRANSLATION_SKILL: 翻译技能
"""

from app.skills.library.data_analysis import DATA_ANALYSIS_SKILL
from app.skills.library.code_generation import CODE_GENERATION_SKILL
from app.skills.library.text_writing import TEXT_WRITING_SKILL
from app.skills.library.translation import TRANSLATION_SKILL

__all__ = [
    "DATA_ANALYSIS_SKILL",
    "CODE_GENERATION_SKILL",
    "TEXT_WRITING_SKILL",
    "TRANSLATION_SKILL",
    "register_all_builtin_skills",
]


def register_all_builtin_skills(skill_manager) -> None:
    """
    将所有内置技能注册到 SkillManager 中
    
    这是一个便捷函数，供 API 端点等模块在初始化时调用，
    一次性将所有内置技能注册到技能管理器，无需逐个手动注册。
    
    Args:
        skill_manager: SkillManager 实例，用于接收技能注册
        
    使用示例：
        from app.skills.manager import SkillManager
        from app.skills.library import register_all_builtin_skills
        
        skill_manager = SkillManager()
        register_all_builtin_skills(skill_manager)
    """
    from loguru import logger
    from colorama import Fore, Style
    
    # NOTE: 将所有内置技能逐一注册到技能管理器中，方便统一管理和追踪
    builtin_skills = [
        DATA_ANALYSIS_SKILL,
        CODE_GENERATION_SKILL,
        TEXT_WRITING_SKILL,
        TRANSLATION_SKILL,
    ]
    
    for skill in builtin_skills:
        skill_manager.register_skill(skill)
        logger.debug(f"{Fore.GREEN}已注册内置技能: {skill.name} ({skill.skill_id}){Style.RESET_ALL}")
    
    logger.info(
        f"{Fore.GREEN}所有内置技能注册完成，共注册 {len(builtin_skills)} 个技能{Style.RESET_ALL}"
    )
