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
    SkillInfo, SkillParamSchema
)
from app.schemas.common_data import ApiResponseData, PlatformEnum
from app.skills.manager import SkillManager
from app.utils.dependencies import get_skill_manager

# 创建路由器
router = APIRouter()


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
        skills_info = []
        for skill in skills:
            # NOTE: 将 Skill 模型的 param_schemas 转换为 API 层的 SkillParamSchema 格式
            # key 为参数名（对应 prompt_template 中 {key}），value 包含说明和示例
            api_param_schemas = {
                param_name: SkillParamSchema(
                    label=param_schema.label,
                    description=param_schema.description,
                    examples=param_schema.examples,
                    required=param_schema.required
                )
                for param_name, param_schema in skill.param_schemas.items()
            }
            logger.debug(
                f"{Fore.CYAN}[技能列表] {skill.skill_id} 包含 {len(api_param_schemas)} 个参数元数据{Style.RESET_ALL}"
            )
            skills_info.append(
                SkillInfo(
                    skill_id=skill.skill_id,
                    name=skill.name,
                    description=skill.description,
                    required_tools=skill.required_tools,
                    optional_tools=skill.optional_tools,
                    tags=skill.tags,
                    param_schemas=api_param_schemas
                )
            )
        
        logger.info(f"{Fore.GREEN}成功列出 {len(skills_info)} 个技能，参数元数据已携带{Style.RESET_ALL}")
        
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
        # NOTE: InferenceEngine 需要 provider 和 model_registry 两个必填参数
        # 与 agents.py 和 chat.py 保持一致的初始化方式
        from app.llm_hub.providers.openai import OpenAIProvider
        from app.llm_hub.registry import ModelRegistry
        from app.core.config import settings
        
        provider = OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL
        )
        model_registry = ModelRegistry()
        inference_engine = InferenceEngine(
            provider=provider,
            model_registry=model_registry
        )
        logger.info(f"{Fore.CYAN}技能执行 - 已创建 InferenceEngine{Style.RESET_ALL}")
        
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
