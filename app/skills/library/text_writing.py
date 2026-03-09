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
from app.skills.base import Skill, MemoryStrategy, ParamSchema

# 文本写作技能定义
TEXT_WRITING_SKILL = Skill(
    skill_id="text_writing",
    name="文本写作",
    # NOTE: 描述中明确声明"不写入本地文件"——防止 LLM 规划时误解为文件写入工具。
    # 本技能仅生成文本内容（返回字符串），实际文件保存必须由 file_write 工具完成。
    description="专业文本写作，支持多种类型和风格。【重要】本技能只生成文本内容，不具备任何写入本地文件的能力，不会在磁盘上创建文件。若需将生成的内容保存到本地文件，必须在后续步骤中调用 file_write 工具",
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

【重要提醒】本技能只负责生成文本内容。若需将文本保存到本地文件，请在计划中另外添加 file_write 工具步骤完成实际写入。

请直接输出最终文本内容。
""",
    required_tools=[],
    optional_tools=[],
    memory_strategy=MemoryStrategy(include_short_term=False),
    tags=["写作", "文本", "创作", "内容"],

    examples=[],
    # NOTE: 参数元数据，告知前端每个参数的含义和示例，帮助用户快速填写
    param_schemas={
        "topic": ParamSchema(
            label="写作主题",
            description="文章的核心主题或标题，描述越清晰内容越精准",
            examples=[
                "人工智能对职场未来的影响",
                "如何培养高效的时间管理习惯",
                "新能源汽车行业的发展现状与趋势"
            ],
            required=True
        ),
        "content_type": ParamSchema(
            label="文本类型",
            description="要写作的文本类型，决定整体结构和格式",
            examples=["博客文章", "产品介绍", "工作报告", "商业邮件", "学术论文摘要", "社交媒体推文"],
            required=True
        ),
        "style": ParamSchema(
            label="写作风格",
            description="文章的语气和风格，影响语言表达方式",
            examples=["正式专业", "轻松易懂", "学术严谨", "幽默风趣", "激励人心"],
            required=True
        ),
        "word_count": ParamSchema(
            label="字数要求",
            description="目标字数或字数范围",
            examples=["500字以内", "800-1200字", "2000字左右", "不限字数，内容完整即可"],
            required=True
        )
    }
)

logger.info(f"{Fore.GREEN}[文本写作技能] TEXT_WRITING_SKILL 已定义，参数元数据加载完成{Style.RESET_ALL}")

