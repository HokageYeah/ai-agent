from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field, ConfigDict
from sys import stdout
from loguru import logger
from colorama import Fore, Style

# 配置 Loguru
logger.remove()
logger.add(stdout, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>")


class ParamSchema(BaseModel):
    """
    技能参数元数据定义
    
    用于描述 prompt_template 中每个 {variable} 参数的含义和示例，
    前端弹框展示时显示在对应输入框下方，帮助用户快速理解并填写参数。
    """
    # 参数名称（与 prompt_template 中 {key} 对应）
    label: str = Field(..., description="参数中文名称，展示在输入框标签处")
    description: str = Field(..., description="参数功能说明，帮助用户理解该参数作用")
    # 示例值列表，前端可直接点击填入
    examples: List[str] = Field(default_factory=list, description="参数示例值列表，前端点击可快捷填入")
    # 是否为必填参数
    required: bool = Field(True, description="是否为必填参数")


class MemoryStrategy(BaseModel):
    """
    记忆策略配置
    
    决定技能执行时如何使用上下文记忆
    """
    include_short_term: bool = Field(True, description="是否包含短期对话记忆")
    # 可以扩展长期记忆等其他策略

class Skill(BaseModel):
    """
    技能定义数据模型
    
    技能是预定义的能力单元，包含 Prompt 模板和工具依赖
    """
    skill_id: str = Field(..., description="技能唯一标识")
    name: str = Field(..., description="技能名称")
    description: str = Field(..., description="技能描述")
    prompt_template: str = Field(..., description="Prompt 模板，支持 {variable} 格式插值")
    required_tools: List[str] = Field(default_factory=list, description="依赖的工具名称列表")
    optional_tools: List[str] = Field(default_factory=list, description="可选的工具名称列表")
    memory_strategy: MemoryStrategy = Field(default_factory=lambda: MemoryStrategy(), description="记忆策略")
    tags: List[str] = Field(default_factory=list, description="技能标签")
    examples: List[Dict[str, Any]] = Field(default_factory=list, description="Few-shot 示例")
    # NOTE: 每个 prompt_template 变量对应的参数说明和示例，key 为变量名（不含花括号）
    param_schemas: Dict[str, ParamSchema] = Field(
        default_factory=dict,
        description="参数元数据字典，key 为参数名，value 为参数描述与示例"
    )
    # NOTE: 以下字段用于“技能包动态加载”模式，兼容旧版硬编码技能模型。
    # source_path: 记录技能来源文件路径，便于排障和前端展示。
    source_path: Optional[str] = Field(None, description="技能来源 SKILL.md 路径")
    # instruction_markdown: 保留技能完整说明正文，供运行时拼装 Prompt 使用。
    instruction_markdown: str = Field("", description="技能完整说明 Markdown 正文")
    # scripts/resources: 技能包中声明的脚本与资源路径（相对技能目录）
    scripts: List[str] = Field(default_factory=list, description="技能脚本路径列表")
    resources: List[str] = Field(default_factory=list, description="技能资源路径列表")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "skill_id": "data_analysis",
                "name": "Data Analysis",
                "description": "Analyze datasets and provide insights.",
                "prompt_template": "Analyze the following data: {data}",
                "required_tools": ["python_executor"],
                "source_path": "app/skills/skills_md/data_analysis/SKILL.md",
                "scripts": [],
                "resources": ["resources/param_schemas.json"]
            }
        }
    )


class SkillMetadata(BaseModel):
    """
    技能轻量元数据

    该模型用于“发现阶段”，仅承载路由所需的低成本信息，
    避免在启动时加载完整技能正文与资源文件。
    """

    skill_id: str = Field(..., description="技能唯一标识")
    name: str = Field(..., description="技能显示名称")
    description: str = Field(..., description="技能描述")
    source_path: str = Field(..., description="SKILL.md 文件路径")
    when_to_use: List[str] = Field(default_factory=list, description="使用场景列表")
    inputs: List[str] = Field(default_factory=list, description="输入参数名列表")
    input_descriptions: Dict[str, str] = Field(
        default_factory=dict,
        description="输入参数说明，key=参数名，value=说明"
    )
    required_tools: List[str] = Field(default_factory=list, description="必需工具")
    optional_tools: List[str] = Field(default_factory=list, description="可选工具")
    tags: List[str] = Field(default_factory=list, description="技能标签")
    memory_include_short_term: bool = Field(True, description="是否包含短期记忆")
    scripts: List[str] = Field(default_factory=list, description="脚本路径列表")
    resources: List[str] = Field(default_factory=list, description="资源路径列表")
