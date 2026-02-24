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
from app.skills.base import Skill, MemoryStrategy, ParamSchema

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
    examples=[],
    # NOTE: 参数元数据，告知前端每个参数的含义和示例，帮助用户快速填写
    param_schemas={
        "requirements": ParamSchema(
            label="需求描述",
            description="详细描述你要实现的功能需求，越清晰越好",
            examples=[
                "实现一个用户登录接口，包含手机号+密码验证，返回 JWT Token",
                "写一个爬取豆瓣电影 Top250 的爬虫，保存为 CSV 文件",
                "实现二叉树的前序、中序、后序遍历，要求递归和迭代两种方式"
            ],
            required=True
        ),
        "language": ParamSchema(
            label="编程语言",
            description="目标编程语言",
            examples=["Python", "TypeScript", "Go", "Java", "Rust", "JavaScript"],
            required=True
        ),
        "framework": ParamSchema(
            label="框架/库",
            description="使用的框架或第三方库，无特定要求可填写「无」或「标准库」",
            examples=["FastAPI", "Vue 3 + TypeScript", "React + Hooks", "无，使用标准库", "Spring Boot"],
            required=True
        )
    }
)

logger.info(f"{Fore.GREEN}[代码生成技能] CODE_GENERATION_SKILL 已定义，参数元数据加载完成{Style.RESET_ALL}")

