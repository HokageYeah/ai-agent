"""
文本写作技能模块

本模块定义了文本写作技能，用于专业文本创作。

功能特点:
1. 支持多种文本类型（文章、报告、邮件等）
2. 可定制写作风格（正式、轻松、学术等）
3. 满足字数要求
4. 结构清晰、逻辑连贯
5. 语言表达专业

无需工具依赖，纯文本生成任务。
"""

from loguru import logger
from colorama import Fore, Style
from app.skills.base import Skill, MemoryStrategy

# 文本写作技能定义
TEXT_WRITING_SKILL = Skill(
    skill_id="text_writing",
    name="文本写作",
    description="专业文本写作，支持多种类型和风格",
    prompt_template="""你是一个专业的文本创作者。请根据以下要求撰写文本:

写作主题:
{topic}

文本类型:
{content_type}

写作风格:
{style}

字数要求:
{word_count}

写作要求:
1. 主题明确 - 紧扣主题，不偏离核心内容
2. 结构清晰 - 使用适当的段落划分和标题
3. 逻辑连贯 - 段落之间逻辑流畅，过渡自然
4. 语言准确 - 用词精准，表达专业
5. 符合风格 - 严格按照指定的写作风格进行创作

请直接输出最终文本内容。
""",
    required_tools=[],
    optional_tools=[],
    memory_strategy=MemoryStrategy(include_short_term=False),
    tags=["写作", "文本", "创作", "内容"],
    examples=[]
)

logger.info(f"{Fore.GREEN}[文本写作技能] TEXT_WRITING_SKILL 已定义{Style.RESET_ALL}")
