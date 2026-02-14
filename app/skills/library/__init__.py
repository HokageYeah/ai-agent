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
]
