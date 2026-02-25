"""
Automation API Schema Definitions (自动化服务数据模型)
====================================================

本模块定义了自动化服务相关的请求与响应数据模型（Pydantic Schema）。

包含的数据模型：
  1. DataProcessingRequest    - 数据处理请求
  2. ReportGenerationRequest  - 报告生成请求
  3. CodeGenerationRequest    - 代码生成请求

作者: AI Agent Team
创建时间: 2026-02-25
"""

from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field


# ============================================================================
# 参数元数据（用于前端展示参数说明和示例）
# ============================================================================

class AutomationParamSchema(BaseModel):
    """
    自动化服务参数元数据
    
    用于前端展示参数的说明、标签和示例。
    """
    label: str = Field(..., description="参数的中文标签")
    description: str = Field(..., description="参数的详细说明")
    examples: List[str] = Field(default_factory=list, description="参数示例值")
    required: bool = Field(default=True, description="是否为必填参数")


# ============================================================================
# 各服务类型的参数元数据定义
# ============================================================================

# 数据处理服务参数元数据
DATA_PROCESSING_PARAMS: Dict[str, AutomationParamSchema] = {
    "data": AutomationParamSchema(
        label="待处理数据",
        description="需要处理的数据，支持 JSON、文本、数组等格式。例如：待清洗的原始数据、需要转换格式的文档内容等。",
        examples=[
            '{"name": "张三", "age": 25, "city": "北京"}',
            "[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]",
            "这是一段需要分析的文本内容..."
        ],
        required=True
    ),
    "processing_config": AutomationParamSchema(
        label="处理配置",
        description="数据处理的额外配置选项，如处理模式、输出格式等。可选，不填使用默认配置。",
        examples=[
            '{"mode": "auto", "output": "json"}',
            '{"validate": true, "strict": false}',
            '{"format": "csv", "encoding": "utf-8"}'
        ],
        required=False
    ),
}

# 报告生成服务参数元数据
REPORT_GENERATION_PARAMS: Dict[str, AutomationParamSchema] = {
    "data_source": AutomationParamSchema(
        label="数据源",
        description="用于生成报告的数据来源，可以是数据描述、统计信息、分析结果等。",
        examples=[
            "本月销售额共计 50 万元，较上月增长 20%，客户新增 100 人",
            "2024年第一季度：收入 100 万，成本 60 万，利润 40 万",
            "网站访问量：日均 PV 10000，UV 3000，跳出率 45%"
        ],
        required=True
    ),
    "template": AutomationParamSchema(
        label="报告模板",
        description="报告的模板类型，如不指定则自动选择合适的模板。",
        examples=[
            "月度运营报告",
            "数据分析报告",
            "周报"
        ],
        required=False
    ),
    "report_config": AutomationParamSchema(
        label="报告配置",
        description="报告生成的额外配置，如标题、格式、样式等。",
        examples=[
            '{"title": "2024年Q1运营报告", "format": "markdown"}',
            '{"include_chart": true, "theme": "professional"}',
            '{"language": "zh-CN", "style": "brief"}'
        ],
        required=False
    ),
}

# 代码生成服务参数元数据
CODE_GENERATION_PARAMS: Dict[str, AutomationParamSchema] = {
    "requirements": AutomationParamSchema(
        label="代码需求描述",
        description="详细描述需要生成的代码功能、逻辑、要求等。描述越详细，生成的代码质量越高。",
        examples=[
            "用 Python 写一个计算斐波那契数列的函数，支持指定返回前 N 个数字",
            "使用 React 写一个带搜索功能的用户列表组件，支持分页",
            "用 Go 实现一个简单的 HTTP 服务器，支持 GET 和 POST 请求"
        ],
        required=True
    ),
    "language": AutomationParamSchema(
        label="编程语言",
        description="生成代码所使用的编程语言。",
        examples=["Python", "JavaScript", "TypeScript", "Go", "Java"],
        required=True
    ),
    "framework": AutomationParamSchema(
        label="框架",
        description="使用的框架或库，如不指定则使用该语言的主流框架或原生实现。",
        examples=[
            "FastAPI",
            "React + TypeScript",
            "Django",
            "Vue 3"
        ],
        required=False
    ),
    "code_config": AutomationParamSchema(
        label="代码配置",
        description="代码生成的额外配置，如是否包含注释、测试代码、错误处理等。",
        examples=[
            '{"add_comments": true, "add_tests": true}',
            '{"error_handling": true, "logging": true}',
            '{"typescript_strict": true, "eslint": true}'
        ],
        required=False
    ),
}


# ============================================================================
# 请求模型
# ============================================================================

class DataProcessingRequest(BaseModel):
    """
    数据处理请求模型
    
    用于提交待处理的数据及处理配置。
    
    Attributes:
        data: 待处理的数据，支持任意类型
        processing_config: 处理配置，默认为空字典
    """
    data: Any = Field(..., description="待处理的数据")
    processing_config: Dict[str, Any] = Field(default_factory=dict, description="处理配置")


class ReportGenerationRequest(BaseModel):
    """
    报告生成请求模型
    
    用于提交数据源和模板信息，生成相应报告。
    
    Attributes:
        data_source: 数据源描述或内容
        template: 报告模板，可选
        report_config: 报告配置，默认为空字典
    """
    data_source: str = Field(..., description="数据源描述或内容")
    template: Optional[str] = Field(None, description="报告模板")
    report_config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="报告配置")


class CodeGenerationRequest(BaseModel):
    """
    代码生成请求模型
    
    用于提交代码需求，生成相应代码。
    
    Attributes:
        requirements: 代码需求描述
        language: 编程语言，默认为 Python
        framework: 使用的框架，可选
        code_config: 生成配置，默认为空字典
    """
    requirements: str = Field(..., description="代码需求描述")
    language: str = Field("Python", description="编程语言")
    framework: Optional[str] = Field(None, description="使用的框架")
    code_config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="生成配置")


# ============================================================================
# 自动化服务类型定义（用于列表展示）
# ============================================================================

class AutomationServiceInfo(BaseModel):
    """
    自动化服务信息
    
    用于前端展示服务列表和参数元数据。
    """
    type: str = Field(..., description="服务类型标识")
    name: str = Field(..., description="服务名称")
    description: str = Field(..., description="服务描述")
    icon: str = Field(..., description="服务图标")
    color: str = Field(..., description="服务颜色（渐变色）")
    param_schemas: Dict[str, AutomationParamSchema] = Field(..., description="参数元数据")


# 获取所有自动化服务信息
def get_automation_services() -> list[AutomationServiceInfo]:
    """
    获取所有自动化服务信息列表
    
    Returns:
        包含所有服务及其参数元数据的列表
    """
    return [
        AutomationServiceInfo(
            type="data_processing",
            name="数据处理",
            description="对输入数据进行自动化处理、清洗、转换等操作",
            icon="DataAnalysis",
            color="linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
            param_schemas=DATA_PROCESSING_PARAMS
        ),
        AutomationServiceInfo(
            type="report_generation",
            name="报告生成",
            description="基于数据源自动生成各类报告、摘要、分析文档",
            icon="Reading",
            color="linear-gradient(135deg, #f093fb 0%, #f5576c 100%)",
            param_schemas=REPORT_GENERATION_PARAMS
        ),
        AutomationServiceInfo(
            type="code_generation",
            name="代码生成",
            description="根据需求描述自动生成代码，支持多种编程语言和框架",
            icon="Notebook",
            color="linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)",
            param_schemas=CODE_GENERATION_PARAMS
        ),
    ]
