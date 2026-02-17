"""
Skills 和 Tools API 测试
================================

本模块测试技能和工具相关的 REST API 端点。

测试内容：
1. GET /skills - 列出所有技能
2. POST /skills/{skill_id}/execute - 执行技能
3. GET /tools - 列出所有工具

作者: AI Agent Team
创建时间: 2026-02-17
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


class TestSkillsAPI:
    """Skills API 测试类"""
    
    @pytest.mark.asyncio
    async def test_list_skills_endpoint(self):
        """测试列出所有技能接口"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/skills")
            
            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            assert "ret" in data
            assert "success" in data["ret"]
            
            # 验证返回了技能列表
            skills = data["data"]
            assert isinstance(skills, list)
            assert len(skills) > 0
            
            # 验证每个技能的结构
            for skill in skills:
                assert "skill_id" in skill
                assert "name" in skill
                assert "description" in skill
                assert "required_tools" in skill
    
    @pytest.mark.asyncio
    async def test_execute_skill_endpoint(self):
        """测试执行技能接口"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 使用文本写作技能
            skill_id = "text_writing"
            
            request_data = {
                "parameters": {
                    "topic": "春天",
                    "content_type": "诗歌",
                    "style": "现代诗",
                    "word_count": "100字左右"
                },
                "config": {
                    "model": "gpt-3.5-turbo",
                    "temperature": 0.8
                }
            }
            
            response = await client.post(
                f"/api/v1/skills/{skill_id}/execute",
                json=request_data
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "success" in data["ret"]
            
            # 验证执行结果
            result = data["data"]
            assert "skill_id" in result
            assert "skill_name" in result
            assert "result" in result
            assert "success" in result
            assert result["skill_id"] == skill_id
    
    @pytest.mark.asyncio
    async def test_execute_translation_skill(self):
        """测试执行翻译技能"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            skill_id = "translation"
            
            request_data = {
                "parameters": {
                    "text": "Hello, how are you?",
                    "target_language": "中文"
                },
                "config": {}
            }
            
            response = await client.post(
                f"/api/v1/skills/{skill_id}/execute",
                json=request_data
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "success" in data["ret"]
    
    @pytest.mark.asyncio
    async def test_execute_nonexistent_skill(self):
        """测试执行不存在的技能"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            request_data = {
                "parameters": {"test": "data"},
                "config": {}
            }
            
            response = await client.post(
                "/api/v1/skills/nonexistent_skill/execute",
                json=request_data
            )
            
            # 应该返回 404 错误
            assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_skill_error_handling(self):
        """测试技能 API 错误处理"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            skill_id = "text_writing"
            
            # 测试缺少必需字段
            invalid_data = {
                # 缺少 parameters 字段
                "config": {}
            }
            
            response = await client.post(
                f"/api/v1/skills/{skill_id}/execute",
                json=invalid_data
            )
            
            # 应该返回 422 验证错误
            assert response.status_code == 422


class TestToolsAPI:
    """Tools API 测试类"""
    
    @pytest.mark.asyncio
    async def test_list_tools_endpoint(self):
        """测试列出所有工具接口"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/tools")
            
            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            assert "ret" in data
            assert "success" in data["ret"]
            
            # 验证返回了工具列表
            tools = data["data"]
            assert isinstance(tools, list)
            assert len(tools) > 0
            
            # 验证每个工具的结构
            for tool in tools:
                assert "name" in tool
                assert "description" in tool
                assert "parameters" in tool
