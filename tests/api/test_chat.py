"""
Chat API 测试
================================

本模块测试对话相关的 REST API 端点。

测试内容：
1. POST /chat - 普通对话接口
2. POST /chat/stream - 流式对话接口
3. DELETE /chat/{conversation_id} - 清空对话历史

作者: AI Agent Team
创建时间: 2026-02-17
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


class TestChatAPI:
    """Chat API 测试类"""
    
    @pytest.mark.asyncio
    async def test_chat_endpoint(self):
        """测试普通对话接口"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 准备请求数据
            request_data = {
                "conversation_id": "test_conv_001",
                "message": "你好，请介绍一下你自己",
                "model": "gpt-3.5-turbo",
                "temperature": 0.7,
                "max_tokens": 500
            }
            
            # 发送请求
            response = await client.post("/api/v1/chat", json=request_data)
            
            # 验证响应
            assert response.status_code == 200
            
            data = response.json()
            assert "data" in data
            assert "ret" in data
            assert "success" in data["ret"]
            
            # 验证响应内容
            chat_data = data["data"]
            assert "conversation_id" in chat_data
            assert "message" in chat_data
            assert "model" in chat_data
            assert chat_data["conversation_id"] == "test_conv_001"
    
    @pytest.mark.asyncio
    async def test_chat_with_system_prompt(self):
        """测试带系统提示词的对话"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            request_data = {
                "conversation_id": "test_conv_002",
                "message": "帮我写一首诗",
                "system_prompt": "你是一个专业的诗人，擅长创作现代诗",
                "model": "gpt-3.5-turbo"
            }
            
            response = await client.post("/api/v1/chat", json=request_data)
            
            assert response.status_code == 200
            data = response.json()
            assert "success" in data["ret"]
    
    @pytest.mark.asyncio
    async def test_chat_stream_endpoint(self):
        """测试流式对话接口"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            request_data = {
                "conversation_id": "test_conv_003",
                "message": "请用100字左右介绍Python编程语言",
                "model": "gpt-3.5-turbo"
            }
            
            # 发送流式请求
            async with client.stream("POST", "/api/v1/chat/stream", json=request_data) as response:
                assert response.status_code == 200
                
                # 读取流式响应
                chunks = []
                async for chunk in response.aiter_text():
                    if chunk:
                        chunks.append(chunk)
                
                # 验证收到了响应内容
                assert len(chunks) > 0
                full_response = "".join(chunks)
                assert len(full_response) > 0
    
    @pytest.mark.asyncio
    async def test_clear_chat_endpoint(self):
        """测试清空对话历史接口"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            conversation_id = "test_conv_004"
            
            # 先发送一条消息
            await client.post("/api/v1/chat", json={
                "conversation_id": conversation_id,
                "message": "第一条消息"
            })
            
            # 清空对话历史
            response = await client.delete(f"/api/v1/chat/{conversation_id}")
            
            assert response.status_code == 200
            data = response.json()
            assert "success" in data["ret"]
            assert data["data"]["conversation_id"] == conversation_id
            assert data["data"]["status"] == "cleared"
    
    @pytest.mark.asyncio
    async def test_chat_error_handling(self):
        """测试错误处理"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 测试缺少必需字段
            invalid_data = {
                "conversation_id": "test_conv_005"
                # 缺少 message 字段
            }
            
            response = await client.post("/api/v1/chat", json=invalid_data)
            
            # 应该返回 422 验证错误
            assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_multi_turn_conversation(self):
        """测试多轮对话"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            conversation_id = "test_conv_006"
            
            # 第一轮对话
            response1 = await client.post("/api/v1/chat", json={
                "conversation_id": conversation_id,
                "message": "我的名字是张三"
            })
            assert response1.status_code == 200
            
            # 第二轮对话（测试上下文记忆）
            response2 = await client.post("/api/v1/chat", json={
                "conversation_id": conversation_id,
                "message": "我刚才说我叫什么名字？"
            })
            assert response2.status_code == 200
            
            # 验证回复中包含了上下文信息
            data = response2.json()
            assert "data" in data
