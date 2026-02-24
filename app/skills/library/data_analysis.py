"""
数据分析技能模块

本模块定义了数据分析技能，用于分析数据并生成洞察。

功能特点:
1. 识别数据中的关键趋势
2. 发现异常值和模式
3. 提供可行的建议

依赖工具:
- python_executor: 用于执行数据分析代码
"""

from loguru import logger
from colorama import Fore, Style
from app.skills.base import Skill, MemoryStrategy, ParamSchema

# 数据分析技能定义
DATA_ANALYSIS_SKILL = Skill(
    skill_id="data_analysis",
    name="数据分析",
    description="分析数据并生成洞察，识别趋势、发现异常值并提供建议",
    prompt_template="""你是一个专业的数据分析专家。请分析以下数据:

{data}

分析要求:
1. 识别关键趋势 - 找出数据中的主要变化模式和趋势
2. 发现异常值 - 检测数据中的异常点和离群值
3. 提供可行建议 - 基于分析结果提供实用的改进建议

请使用 Python 代码进行数据分析，并提供详细的分析报告。
分析报告应包含:
- 数据概览（数据量、字段、类型等）
- 统计分析（均值、中位数、标准差等）
- 趋势分析
- 异常检测
- 结论和建议
""",
    required_tools=["python_executor"],
    optional_tools=[],
    memory_strategy=MemoryStrategy(include_short_term=True),
    tags=["分析", "数据", "统计", "可视化"],
    examples=[],
    # NOTE: 参数元数据，告知前端每个参数的含义和示例，帮助用户快速填写
    param_schemas={
        "data": ParamSchema(
            label="数据内容",
            description="需要分析的数据，可以是 CSV 格式、JSON 格式、数字列表或表格文本",
            examples=[
                "月份,销售额,利润\n1月,12000,3000\n2月,15000,4200\n3月,9800,1500\n4月,18000,5600",
                "[120, 135, 98, 210, 88, 176, 145, 230, 167, 199]",
                "产品A季度销量：Q1=5000, Q2=7200, Q3=6800, Q4=9500"
            ],
            required=True
        )
    }
)

logger.info(f"{Fore.GREEN}[数据分析技能] DATA_ANALYSIS_SKILL 已定义，参数元数据加载完成{Style.RESET_ALL}")

