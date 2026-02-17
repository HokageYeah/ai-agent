"""
Agent API 测试
================================

本模块测试 Agent 相关的 REST API 端点。

测试内容：
1. POST /agents/{agent_id}/execute - 执行 Agent
2. GET /agents - 列出所有 Agent
3. GET /agents/{agent_id} - 获取 Agent 详情

作者: AI Agent Team
创建时间: 2026-02-17
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


class TestAgentAPI:
    """Agent API 测试类"""
    
    @pytest.mark.asyncio
    async def test_list_agents_endpoint(self):
        """测试列出所有 Agent 接口"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/agents")
            
            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            assert "ret" in data
            assert "success" in data["ret"]
            
            # 验证返回了 Agent 列表
            agents = data["data"]
            assert isinstance(agents, list)
            assert len(agents) > 0
            
            # 验证每个 Agent 的结构
            for agent in agents:
                assert "agent_id" in agent
                assert "name" in agent
                assert "description" in agent
                assert "capabilities" in agent
                assert "available_tools" in agent
                assert "available_skills" in agent
    
    @pytest.mark.asyncio
    async def test_get_agent_detail_endpoint(self):
        """测试获取 Agent 详情接口"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 先获取所有 Agent 列表
            list_response = await client.get("/api/v1/agents")
            agents = list_response.json()["data"]
            
            if len(agents) > 0:
                agent_id = agents[0]["agent_id"]
                
                # 获取该 Agent 的详情
                response = await client.get(f"/api/v1/agents/{agent_id}")
                
                assert response.status_code == 200
                data = response.json()
                assert "success" in data["ret"]
                
                # 验证详情包含更多信息
                agent_detail = data["data"]
                assert agent_detail["agent_id"] == agent_id
                assert "role" in agent_detail
                assert "agent_config" in agent_detail
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_agent(self):
        """测试获取不存在的 Agent"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/agents/nonexistent_agent_id")
            
            # 应该返回 404 错误
            assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_execute_agent_endpoint(self):
        """测试执行 Agent 接口"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 使用客服主 Agent
            agent_id = "cs_master"
            
            request_data = {
                "task": "帮我查询订单状态",
                "conversation_history": [],
                "config": {}
            }
            
            response = await client.post(
                f"/api/v1/agents/{agent_id}/execute",
                json=request_data
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "success" in data["ret"]
            
            # 验证执行结果
            result = data["data"]
            assert "agent_id" in result
            assert "agent_name" in result
            assert "task" in result
            assert "result" in result
            assert "iterations" in result
            assert "success" in result
            assert result["agent_id"] == agent_id
    
    @pytest.mark.asyncio
    async def test_execute_agent_with_history(self):
        """测试带对话历史的 Agent 执行"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            agent_id = "order_agent"
            
            request_data = {
                "task": "我想查询我的订单",
                "conversation_history": [
                    {"role": "user", "content": "你好"},
                    {"role": "assistant", "content": "你好，我是订单专员，有什么可以帮您？"}
                ],
                "config": {}
            }
            
            response = await client.post(
                f"/api/v1/agents/{agent_id}/execute",
                json=request_data
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "success" in data["ret"]
    
    @pytest.mark.asyncio
    async def test_execute_nonexistent_agent(self):
        """测试执行不存在的 Agent"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            request_data = {
                "task": "测试任务",
                "conversation_history": []
            }
            
            response = await client.post(
                "/api/v1/agents/nonexistent_agent/execute",
                json=request_data
            )
            
            # 应该返回 404 错误
            assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_agent_error_handling(self):
        """测试 Agent API 错误处理"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            agent_id = "cs_master"
            
            # 测试缺少必需字段
            invalid_data = {
                # 缺少 task 字段
                "conversation_history": []
            }
            
            response = await client.post(
                f"/api/v1/agents/{agent_id}/execute",
                json=invalid_data
            )
            
            # 应该返回 422 验证错误
            assert response.status_code == 422
