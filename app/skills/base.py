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


class SkillRuntimeDependency(BaseModel):
    """
    技能运行时依赖声明

    设计说明：
    1. 依赖声明写在 SKILL.md frontmatter 中，便于技能自描述；
    2. 执行引擎会在真正调用 LLM 前先做“检查 -> 缺失则安装 -> 安装后复检”；
    3. 当前先支持 npm / shell 两类，后续可继续扩展而不破坏旧技能。
    """

    type: str = Field(..., description="依赖类型，例如 npm / shell")
    tool_name: Optional[str] = Field(
        default=None,
        description="执行依赖检查/安装所需的工具名；为空时按 type 自动推导",
    )
    packages: List[str] = Field(
        default_factory=list,
        description="包管理器依赖列表，例如 npm 包名列表",
    )
    check_command: Optional[str] = Field(
        default=None,
        description="自定义检查命令；为空时按 type 自动生成",
    )
    install_command: Optional[str] = Field(
        default=None,
        description="自定义安装命令；为空时按 type 自动生成",
    )
    working_dir: str = Field(
        default=".",
        description="依赖检查/安装的工作目录；相对路径相对于技能目录解析",
    )
    env: Dict[str, str] = Field(
        default_factory=dict,
        description="执行依赖命令时附加的环境变量",
    )
    timeout_seconds: int = Field(
        default=180,
        ge=1,
        le=1800,
        description="单条依赖检查/安装命令超时时间（秒）",
    )
    description: str = Field(
        default="",
        description="依赖说明，便于日志输出和排障",
    )

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
    # NOTE: 声明式输出校验规则列表。每条规则为一个字典，示例：
    #   {"type": "must_contain_any", "markers": ["°C", "温度"], "error": "未返回天气数据"}
    #   {"type": "must_not_contain_any", "markers": ["请告诉我"], "error": "返回了引导话术"}
    # 由 SKILL.md frontmatter 中的 output_validators 字段声明，执行引擎统一解释执行。
    # 这样新增技能时无需修改 Python 代码即可定义个性化的输出校验逻辑。
    output_validators: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="声明式输出校验规则列表，由 SKILL.md frontmatter 定义"
    )
    runtime_dependencies: List[SkillRuntimeDependency] = Field(
        default_factory=list,
        description="技能运行时依赖列表；执行前由执行引擎预检并尝试自动安装",
    )
    
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
    # NOTE: 声明式输出校验规则（与 Skill 模型同步），用于发现阶段透传到执行阶段
    output_validators: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="声明式输出校验规则列表"
    )
    runtime_dependencies: List[SkillRuntimeDependency] = Field(
        default_factory=list,
        description="技能运行时依赖列表"
    )
