"""
Skills API Endpoints (技能接口)
================================

本模块提供技能相关的 REST API 端点。

功能特点：
1. GET /skills - 列出所有技能
2. POST /skills/{skill_id}/execute - 执行技能

作者: AI Agent Team
创建时间: 2026-02-17
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import List
from loguru import logger
from colorama import Fore, Style

from app.schemas.agent_data import (
    SkillExecuteRequest, SkillExecuteResponse,
    SkillInfo
)
from app.schemas.common_data import ApiResponseData, PlatformEnum
from app.skills.manager import SkillManager
from app.llm_hub.inference import InferenceEngine
from app.tools.hub import ToolHub

# 创建路由器
router = APIRouter()

# 全局服务实例
_skill_manager: SkillManager = None


def get_skill_manager() -> SkillManager:
    """
    获取 SkillManager 实例（依赖注入）
    
    Returns:
        SkillManager: 技能管理器实例
    """
    global _skill_manager
    if _skill_manager is None:
        logger.info(f"{Fore.BLUE}初始化 SkillManager...{Style.RESET_ALL}")
        _skill_manager = SkillManager()
        
        # 注册所有内置技能
        from app.skills.library import register_all_builtin_skills
        register_all_builtin_skills(_skill_manager)
        
        logger.info(f"{Fore.GREEN}SkillManager 初始化完成{Style.RESET_ALL}")
    
    return _skill_manager


@router.get("/skills")
async def list_skills(
    skill_manager: SkillManager = Depends(get_skill_manager)
) -> ApiResponseData:
    """
    列出所有技能
    
    Args:
        skill_manager: 技能管理器
        
    Returns:
        ApiResponseData: 统一响应格式
    """
    logger.info(f"{Fore.CYAN}列出所有技能{Style.RESET_ALL}")
    
    try:
        # 获取所有技能
        skills = skill_manager.list_skills()
        
        # 构建响应
        skills_info = [
            SkillInfo(
                skill_id=skill.skill_id,
                name=skill.name,
                description=skill.description,
                required_tools=skill.required_tools,
                optional_tools=skill.optional_tools,
                tags=skill.tags
            )
            for skill in skills
        ]
        
        logger.info(f"{Fore.GREEN}成功列出 {len(skills_info)} 个技能{Style.RESET_ALL}")
        
        return ApiResponseData(
            platform=PlatformEnum.WX_PUBLIC,
            api="/skills",
            data=[info.model_dump() for info in skills_info],
            ret=["success"],
            v=1
        )
        
    except Exception as e:
        logger.error(f"{Fore.RED}列出技能失败: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail=f"列出技能失败: {str(e)}")


@router.post("/skills/{skill_id}/execute")
async def execute_skill(
    skill_id: str,
    request: SkillExecuteRequest,
    skill_manager: SkillManager = Depends(get_skill_manager)
) -> ApiResponseData:
    """
    执行技能
    
    Args:
        skill_id: 技能 ID
        request: 执行请求
        skill_manager: 技能管理器
        
    Returns:
        ApiResponseData: 统一响应格式
    """
    logger.info(f"{Fore.CYAN}接收到技能执行请求 - Skill ID: {skill_id}{Style.RESET_ALL}")
    
    try:
        # 获取技能
        skill = skill_manager.get_skill(skill_id)
        if not skill:
            logger.error(f"{Fore.RED}技能不存在: {skill_id}{Style.RESET_ALL}")
            raise HTTPException(status_code=404, detail=f"技能不存在: {skill_id}")
        
        # 创建执行上下文
        inference_engine = InferenceEngine()
        tool_hub = ToolHub()
        
        # 注册所有内置工具
        from app.tools.builtin import register_all_builtin_tools
        register_all_builtin_tools(tool_hub)
        
        # 构建 Prompt
        prompt = skill.prompt_template.format(**request.parameters)
        
        # 执行推理
        from app.llm_hub.inference import InferenceConfig
        config = InferenceConfig(**request.config) if request.config else InferenceConfig()
        
        result = await inference_engine.infer(
            messages=[{"role": "user", "content": prompt}],
            config=config
        )
        
        logger.info(f"{Fore.GREEN}技能执行成功{Style.RESET_ALL}")
        
        # 构建响应
        response = SkillExecuteResponse(
            skill_id=skill.skill_id,
            skill_name=skill.name,
            result={"content": result.content, "usage": result.usage},
            success=True
        )
        
        return ApiResponseData(
            platform=PlatformEnum.WX_PUBLIC,
            api=f"/skills/{skill_id}/execute",
            data=response.model_dump(),
            ret=["success"],
            v=1
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"{Fore.RED}技能执行失败: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail=f"技能执行失败: {str(e)}")
