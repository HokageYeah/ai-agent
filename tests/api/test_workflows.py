"""
Workflow API 测试
================================

本模块测试工作流相关的 REST API 端点。

测试内容：
1. POST /workflows/{workflow_id}/execute - 执行工作流
2. GET /workflows - 列出所有工作流

作者: AI Agent Team
创建时间: 2026-02-17
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


class TestWorkflowAPI:
    """Workflow API 测试类"""
    
    @pytest.mark.asyncio
    async def test_list_workflows_endpoint(self):
        """测试列出所有工作流接口"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/workflows")
            
            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            assert "ret" in data
            assert "success" in data["ret"]
            
            # 验证返回了工作流列表
            workflows = data["data"]
            assert isinstance(workflows, list)
            
            # 验证每个工作流的结构
            for workflow in workflows:
                assert "workflow_id" in workflow
                assert "name" in workflow
                assert "description" in workflow
                assert "node_count" in workflow
                assert "entry_node" in workflow
                assert "exit_nodes" in workflow
    
    @pytest.mark.asyncio
    async def test_execute_workflow_endpoint(self):
        """测试执行工作流接口"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 使用意图路由工作流
            workflow_id = "intent_routing"
            
            request_data = {
                "input_data": {
                    "user_message": "帮我分析这组数据"
                },
                "config": {}
            }
            
            response = await client.post(
                f"/api/v1/workflows/{workflow_id}/execute",
                json=request_data
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "success" in data["ret"]
            
            # 验证执行结果
            result = data["data"]
            assert "workflow_id" in result
            assert "workflow_name" in result
            assert "result" in result
            assert "success" in result
            assert result["workflow_id"] == workflow_id
    
    @pytest.mark.asyncio
    async def test_execute_nonexistent_workflow(self):
        """测试执行不存在的工作流"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            request_data = {
                "input_data": {"test": "data"},
                "config": {}
            }
            
            response = await client.post(
                "/api/v1/workflows/nonexistent_workflow/execute",
                json=request_data
            )
            
            # 应该返回 404 错误
            assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_workflow_error_handling(self):
        """测试工作流 API 错误处理"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            workflow_id = "intent_routing"
            
            # 测试缺少必需字段
            invalid_data = {
                # 缺少 input_data 字段
                "config": {}
            }
            
            response = await client.post(
                f"/api/v1/workflows/{workflow_id}/execute",
                json=invalid_data
            )
            
            # 应该返回 422 验证错误
            assert response.status_code == 422
