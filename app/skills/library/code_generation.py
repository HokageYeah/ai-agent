"""
代码生成技能模块

本模块定义了代码生成技能，根据需求自动生成高质量代码。

功能特点:
1. 根据需求描述生成代码
2. 支持多种编程语言和框架
3. 代码符合最佳实践
4. 包含必要的注释和文档
5. 处理边界情况

依赖工具:
- python_executor: 用于验证和执行生成的代码
"""

from loguru import logger
from colorama import Fore, Style
from app.skills.base import Skill, MemoryStrategy

# 代码生成技能定义
CODE_GENERATION_SKILL = Skill(
    skill_id="code_generation",
    name="代码生成",
    description="根据需求生成高质量代码，支持多种语言和框架",
    prompt_template="""你是一个资深的软件开发专家。请根据以下需求生成代码:

需求描述:
{requirements}

技术规格:
- 编程语言: {language}
- 框架/库: {framework}

代码要求:
1. 代码符合最佳实践 - 遵循该语言的编码规范和惯例
2. 包含必要的注释 - 添加清晰的中文注释说明关键逻辑
3. 处理边界情况 - 考虑异常情况和边界条件
4. 代码可读性强 - 使用有意义的变量名和函数名
5. 提供使用示例 - 展示如何使用生成的代码

请生成完整、可运行的代码，并在代码后附上简要说明。
如果是 Python 代码，可以使用 python_executor 工具验证代码的正确性。
""",
    required_tools=["python_executor"],
    optional_tools=[],
    memory_strategy=MemoryStrategy(include_short_term=True),
    tags=["编程", "代码", "开发", "自动化"],
    examples=[]
)

logger.info(f"{Fore.GREEN}[代码生成技能] CODE_GENERATION_SKILL 已定义{Style.RESET_ALL}")
