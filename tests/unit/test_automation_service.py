"""
测试 Automation Service
==================

测试自动化服务的各项功能
"""

import pytest
from app.services.automation_service import AutomationService
from app.core.llm_mock import MockLLM
from app.llm_hub.inference import InferenceEngine
from app.llm_hub.registry import ModelRegistry
from app.tools.hub import ToolHub
from app.skills.manager import SkillManager


@pytest.mark.asyncio
async def test_automation_service_initialization():
    """测试 Automation Service 初始化"""
    mock_llm = MockLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    automation_service = AutomationService(llm_hub=inference_engine)
    
    assert automation_service is not None
    assert automation_service.llm_hub is not None


@pytest.mark.asyncio
async def test_data_processing():
    """测试数据处理功能"""
    mock_llm = MockLLM()
    mock_llm.default_response = '{"processed": true, "count": 10}'
    
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    automation_service = AutomationService(llm_hub=inference_engine)
    
    # 测试数据处理
    result = await automation_service.data_processing(
        data={"items": [1, 2, 3, 4, 5]},
        processing_config={
            "task": "统计数据项数量",
            "output_format": "JSON"
        }
    )
    
    assert result is not None
    assert result["success"] is True
    assert "result" in result


@pytest.mark.asyncio
async def test_report_generation():
    """测试报告生成功能"""
    mock_llm = MockLLM()
    mock_llm.default_response = """# 数据分析报告

## 概述
这是一份测试报告。

## 详细分析
数据显示了良好的趋势。

## 结论
测试成功。
"""
    
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    automation_service = AutomationService(llm_hub=inference_engine)
    
    # 测试报告生成
    result = await automation_service.report_generation(
        data_source="测试数据：销售额增长了 20%",
        report_config={
            "title": "销售分析报告",
            "format": "markdown"
        }
    )
    
    assert result is not None
    assert result["success"] is True
    assert "report" in result
    assert result["title"] == "销售分析报告"


@pytest.mark.asyncio
async def test_code_generation():
    """测试代码生成功能"""
    mock_llm = MockLLM()
    mock_llm.default_response = """```python
def hello_world():
    print("Hello, World!")
    
if __name__ == "__main__":
    hello_world()
```"""
    
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    automation_service = AutomationService(llm_hub=inference_engine)
    
    # 测试代码生成
    result = await automation_service.code_generation(
        requirements="创建一个打印 Hello World 的函数",
        language="Python"
    )
    
    assert result is not None
    assert result["success"] is True
    assert "code" in result
    assert result["language"] == "Python"


@pytest.mark.asyncio
async def test_code_generation_with_framework():
    """测试带框架的代码生成"""
    mock_llm = MockLLM()
    mock_llm.default_response = """```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"Hello": "World"}
```"""
    
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=mock_llm, model_registry=registry)
    
    automation_service = AutomationService(llm_hub=inference_engine)
    
    result = await automation_service.code_generation(
        requirements="创建一个简单的 API",
        language="Python",
        framework="FastAPI"
    )
    
    assert result is not None
    assert result["success"] is True
    assert result["framework"] == "FastAPI"


@pytest.mark.asyncio
async def test_automation_service_error_handling():
    """测试错误处理"""
    # 创建一个会抛出异常的 Mock LLM
    class ErrorLLM(MockLLM):
        async def chat(self, messages, **kwargs):
            raise Exception("Test error")
    
    error_llm = ErrorLLM()
    registry = ModelRegistry()
    inference_engine = InferenceEngine(provider=error_llm, model_registry=registry)
    
    automation_service = AutomationService(llm_hub=inference_engine)
    
    # 测试错误处理
    result = await automation_service.data_processing(
        data={"test": "data"},
        processing_config={"task": "test"}
    )
    
    assert result is not None
    assert result["success"] is False
    assert "error" in result
