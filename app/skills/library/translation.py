"""
翻译技能模块

本模块定义了翻译技能，提供高质量的多语言翻译服务。

功能特点:
1. 支持多种语言互译
2. 保持原文风格和语气
3. 确保专业术语准确
4. 符合目标语言的表达习惯
5. 上下文理解准确

无需工具依赖，纯语言转换任务。
"""

from loguru import logger
from colorama import Fore, Style
from app.skills.base import Skill, MemoryStrategy

# 翻译技能定义
TRANSLATION_SKILL = Skill(
    skill_id="translation",
    name="翻译",
    description="多语言翻译，保持原文风格并确保术语准确",
    prompt_template="""你是一个专业的翻译专家。请将以下文本翻译成 {target_language}:

待翻译文本:
{text}

翻译要求:
1. 保持原文风格 - 忠实反映原文的语气、风格和情感
2. 确保专业术语准确 - 使用标准的专业术语翻译
3. 符合目标语言习惯 - 使用地道的目标语言表达方式
4. 上下文理解 - 准确理解文本的上下文和深层含义
5. 格式保持 - 保留原文的段落结构和格式

请直接输出翻译后的文本，不要添加额外说明。
如果原文包含代码、专有名词或特殊格式，请保持不变。
""",
    required_tools=[],
    optional_tools=[],
    memory_strategy=MemoryStrategy(include_short_term=False),
    tags=["翻译", "语言", "多语言", "国际化"],
    examples=[]
)

logger.info(f"{Fore.GREEN}[翻译技能] TRANSLATION_SKILL 已定义{Style.RESET_ALL}")
