"""
阶段六系统集成测试
================================

本模块提供端到端的系统集成测试。

测试内容：
1. 完整对话流程测试
2. Agent 执行流程测试
3. 工作流执行流程测试

作者: AI Agent Team
创建时间: 2026-02-17
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


class TestPhase6Integration:
    """阶段六集成测试类"""
    
    @pytest.mark.asyncio
    async def test_complete_chat_workflow(self):
        """
        端到端测试：完整对话流程
        
        测试流程：
        1. 发起新对话
        2. 进行多轮对话
        3. 测试上下文记忆
        4. 清空对话历史
        """
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            conversation_id = "integration_test_chat_001"
            
            # 1. 第一轮对话
            response1 = await client.post("/api/v1/chat", json={
                "conversation_id": conversation_id,
                "message": "你好，我想了解一下 AI Agent 系统",
                "model": "gpt-3.5-turbo"
            })
            assert response1.status_code == 200
            data1 = response1.json()
            assert "success" in data1["ret"]
            assert "message" in data1["data"]
            
            # 2. 第二轮对话（测试上下文）
            response2 = await client.post("/api/v1/chat", json={
                "conversation_id": conversation_id,
                "message": "刚才我问的是什么？",
                "model": "gpt-3.5-turbo"
            })
            assert response2.status_code == 200
            data2 = response2.json()
            assert "success" in data2["ret"]
            
            # 3. 清空对话历史
            response3 = await client.delete(f"/api/v1/chat/{conversation_id}")
            assert response3.status_code == 200
            data3 = response3.json()
            assert "success" in data3["ret"]
            assert data3["data"]["status"] == "cleared"
    
    @pytest.mark.asyncio
    async def test_agent_execution_workflow(self):
        """
        端到端测试：Agent 执行流程
        
        测试流程：
        1. 列出所有可用 Agent
        2. 获取特定 Agent 详情
        3. 执行 Agent 任务
        4. 验证执行结果
        """
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. 列出所有 Agent
            response1 = await client.get("/api/v1/agents")
            assert response1.status_code == 200
            data1 = response1.json()
            agents = data1["data"]
            assert len(agents) > 0
            
            # 2. 获取客服主 Agent 详情
            agent_id = "cs_master"
            response2 = await client.get(f"/api/v1/agents/{agent_id}")
            assert response2.status_code == 200
            data2 = response2.json()
            agent_detail = data2["data"]
            assert agent_detail["agent_id"] == agent_id
            assert "capabilities" in agent_detail
            
            # 3. 执行 Agent 任务
            response3 = await client.post(
                f"/api/v1/agents/{agent_id}/execute",
                json={
                    "task": "你好，请介绍一下你自己的功能",
                    "conversation_history": [],
                    "config": {}
                }
            )
            assert response3.status_code == 200
            data3 = response3.json()
            assert "success" in data3["ret"]
            result = data3["data"]
            assert result["agent_id"] == agent_id
            assert "result" in result
    
    @pytest.mark.asyncio
    async def test_workflow_execution_workflow(self):
        """
        端到端测试：工作流执行流程
        
        测试流程：
        1. 列出所有可用工作流
        2. 执行意图路由工作流
        3. 验证执行结果
        """
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. 列出所有工作流
            response1 = await client.get("/api/v1/workflows")
            assert response1.status_code == 200
            data1 = response1.json()
            workflows = data1["data"]
            assert len(workflows) > 0
            
            # 2. 执行意图路由工作流
            workflow_id = "intent_routing"
            response2 = await client.post(
                f"/api/v1/workflows/{workflow_id}/execute",
                json={
                    "input_data": {
                        "user_message": "请帮我分析一下这组销售数据"
                    },
                    "config": {}
                }
            )
            assert response2.status_code == 200
            data2 = response2.json()
            assert "success" in data2["ret"]
            result = data2["data"]
            assert result["workflow_id"] == workflow_id
            assert "result" in result
    
    @pytest.mark.asyncio
    async def test_skills_and_tools_integration(self):
        """
        端到端测试：技能和工具系统集成
        
        测试流程：
        1. 列出所有可用技能
        2. 列出所有可用工具
        3. 执行文本写作技能
        4. 验证执行结果
        """
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. 列出所有技能
            response1 = await client.get("/api/v1/skills")
            assert response1.status_code == 200
            data1 = response1.json()
            skills = data1["data"]
            assert len(skills) > 0
            
            # 2. 列出所有工具
            response2 = await client.get("/api/v1/tools")
            assert response2.status_code == 200
            data2 = response2.json()
            tools = data2["data"]
            assert len(tools) > 0
            
            # 3. 执行文本写作技能
            skill_id = "text_writing"
            response3 = await client.post(
                f"/api/v1/skills/{skill_id}/execute",
                json={
                    "parameters": {
                        "topic": "人工智能",
                        "content_type": "说明文",
                        "style": "专业",
                        "word_count": "200字"
                    },
                    "config": {
                        "model": "gpt-3.5-turbo"
                    }
                }
            )
            assert response3.status_code == 200
            data3 = response3.json()
            assert "success" in data3["ret"]
            result = data3["data"]
            assert result["skill_id"] == skill_id
            assert result["success"] is True
    
    @pytest.mark.asyncio
    async def test_full_system_integration(self):
        """
        完整系统集成测试
        
        测试一个完整的用户场景：
        1. 用户通过对话系统提问
        2. 系统使用 Agent 处理复杂任务
        3. Agent 调用技能和工具完成任务
        4. 返回结果给用户
        """
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            conversation_id = "full_integration_test"
            
            # 场景：用户咨询订单问题
            # 1. 用户发起对话
            chat_response = await client.post("/api/v1/chat", json={
                "conversation_id": conversation_id,
                "message": "我想查询我的订单状态",
                "system_prompt": "你是一个智能客服助手",
                "model": "gpt-3.5-turbo"
            })
            assert chat_response.status_code == 200
            
            # 2. 列出可用的 Agent（查看哪个 Agent 可以处理）
            agents_response = await client.get("/api/v1/agents")
            assert agents_response.status_code == 200
            agents = agents_response.json()["data"]
            
            # 找到订单处理 Agent
            order_agent = next(
                (agent for agent in agents if agent["agent_id"] == "order_agent"),
                None
            )
            assert order_agent is not None
            
            # 3. 使用订单 Agent 处理任务
            agent_response = await client.post(
                f"/api/v1/agents/order_agent/execute",
                json={
                    "task": "查询订单号 ORD-12345 的状态",
                    "conversation_history": [],
                    "config": {}
                }
            )
            assert agent_response.status_code == 200
            agent_result = agent_response.json()
            assert "success" in agent_result["ret"]
            
            # 4. 继续对话，基于 Agent 的结果
            followup_response = await client.post("/api/v1/chat", json={
                "conversation_id": conversation_id,
                "message": "谢谢，我明白了",
                "model": "gpt-3.5-turbo"
            })
            assert followup_response.status_code == 200
            
            # 5. 清理对话历史
            clear_response = await client.delete(f"/api/v1/chat/{conversation_id}")
            assert clear_response.status_code == 200
